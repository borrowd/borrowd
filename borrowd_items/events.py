"""
Delivery of lifecycle events to the code that reacts to them.

Each LifecycleEvent is written with the change it describes. Right after that
commits, every registered consumer runs for it, one transaction's events in
order. Whatever a crash or a consumer error leaves behind is picked up by
`manage.py deliver_lifecycle_events`, which cron runs every five minutes.

Delivery is at least once. A consumer records what it handled
(LifecycleEventConsumption) in the same database transaction as its effects,
so a retry skips the consumers that already finished.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any

import sentry_sdk
from django.db import transaction
from django.dispatch import receiver
from django.utils import timezone

from borrowd_users.models import BorrowdUser

from .models import LifecycleEvent, LifecycleEventConsumption, transition_recorded

logger = logging.getLogger("borrowd.items.events")

# After this many failed tries an event is parked until it's replayed or skipped.
MAX_ATTEMPTS = 5
# The sweeper reports when the oldest waiting event is older than this.
LAG_ALERT_AFTER = timedelta(minutes=15)

Consumer = Callable[[LifecycleEvent], None]
_consumers: dict[str, Consumer] = {}


def consumer(name: str) -> Callable[[Consumer], Consumer]:
    """Register a function to run once for every lifecycle event."""

    def register(handler: Consumer) -> Consumer:
        if name in _consumers:
            raise ValueError(f"A lifecycle event consumer named {name!r} exists.")
        _consumers[name] = handler
        return handler

    return register


@receiver(transition_recorded)
def deliver_after_commit(
    sender: type[LifecycleEvent], event: LifecycleEvent, **kwargs: Any
) -> None:
    transaction.on_commit(partial(deliver_pending, event.transaction_id), robust=True)


def deliver_pending(transaction_id: int, *, now: datetime | None = None) -> int:
    """
    Deliver one transaction's waiting events in order and return how many
    went through. Stops at the first one that isn't due, is parked, or is
    being delivered elsewhere; that delivery carries on from there.
    """
    delivered = 0
    while True:
        moment = now or timezone.now()
        with transaction.atomic():
            first = (
                LifecycleEvent.objects.filter(
                    transaction_id=transaction_id, processed_at__isnull=True
                )
                .order_by("revision", "occurred_at")
                .first()
            )
            if first is None:
                return delivered
            event = (
                LifecycleEvent.objects.select_for_update(skip_locked=True)
                .filter(pk=first.pk, processed_at__isnull=True)
                .first()
            )
            if (
                event is None
                or event.failed_at is not None
                or event.next_attempt_at > moment
                or not _deliver(event, moment)
            ):
                return delivered
        delivered += 1


def deliver_due(*, now: datetime | None = None) -> int:
    """Deliver every transaction's due events. This is what cron runs."""
    moment = now or timezone.now()
    transaction_ids = (
        LifecycleEvent.objects.filter(
            processed_at__isnull=True,
            failed_at__isnull=True,
            next_attempt_at__lte=moment,
        )
        .order_by()
        .values_list("transaction_id", flat=True)
        .distinct()
    )
    delivered = sum(deliver_pending(pk, now=moment) for pk in list(transaction_ids))
    _report_lag(moment)
    return delivered


def _deliver(event: LifecycleEvent, now: datetime) -> bool:
    """Run each consumer that hasn't handled the event yet. True if all have."""
    handled = set(
        LifecycleEventConsumption.objects.filter(event=event).values_list(
            "consumer", flat=True
        )
    )
    errors = []
    for name, handler in _consumers.items():
        if name in handled:
            continue
        try:
            with transaction.atomic():
                handler(event)
                LifecycleEventConsumption.objects.create(consumer=name, event=event)
        except Exception as exc:  # one consumer failing must not hold up the rest
            logger.warning("Lifecycle event %s failed in %s: %r", event.pk, name, exc)
            errors.append(f"{name}: {exc!r}")

    event.attempts += 1
    if not errors:
        event.processed_at = now
        event.last_error = ""
        event.save(update_fields=["attempts", "processed_at", "last_error"])
        return True

    event.last_error = "\n".join(errors)
    if event.attempts >= MAX_ATTEMPTS:
        event.failed_at = now
        _report_parked(event)
    else:
        event.next_attempt_at = now + _backoff(event.attempts)
    event.save(update_fields=["attempts", "last_error", "failed_at", "next_attempt_at"])
    return False


def _backoff(attempts: int) -> timedelta:
    # 5, 10, 20, 40 minutes. Cron sweeps every 5, so anything finer is wasted.
    return timedelta(minutes=5 * 2 ** (attempts - 1))


def _report_parked(event: LifecycleEvent) -> None:
    with sentry_sdk.new_scope() as scope:
        scope.set_context(
            "lifecycle_event",
            {
                "event_id": str(event.pk),
                "transaction_id": event.transaction_id,
                "attempts": event.attempts,
                "last_error": event.last_error,
            },
        )
        sentry_sdk.capture_message(
            "Lifecycle event parked after its retries ran out", level="error"
        )


def _report_lag(now: datetime) -> None:
    oldest = (
        LifecycleEvent.objects.filter(processed_at__isnull=True, failed_at__isnull=True)
        .order_by("occurred_at")
        .values_list("occurred_at", flat=True)
        .first()
    )
    if oldest is not None and now - oldest > LAG_ALERT_AFTER:
        with sentry_sdk.new_scope() as scope:
            scope.set_context(
                "lifecycle_events", {"oldest_waiting": oldest.isoformat()}
            )
            sentry_sdk.capture_message(
                "Lifecycle events are waiting longer than expected", level="warning"
            )


@dataclass(frozen=True)
class DeliveryStatus:
    waiting: int
    parked: int
    oldest_waiting: datetime | None


def delivery_status() -> DeliveryStatus:
    """How many events are waiting or parked, and how long the oldest has waited."""
    waiting = LifecycleEvent.objects.filter(
        processed_at__isnull=True, failed_at__isnull=True
    )
    return DeliveryStatus(
        waiting=waiting.count(),
        parked=LifecycleEvent.objects.filter(
            processed_at__isnull=True, failed_at__isnull=False
        ).count(),
        oldest_waiting=waiting.order_by("occurred_at")
        .values_list("occurred_at", flat=True)
        .first(),
    )


def replay(event: LifecycleEvent) -> None:
    """Put a parked or backed-off event back in line and try it now."""
    LifecycleEvent.objects.filter(pk=event.pk, processed_at__isnull=True).update(
        failed_at=None, attempts=0, next_attempt_at=timezone.now()
    )
    deliver_pending(event.transaction_id)


def skip(event: LifecycleEvent, *, by: BorrowdUser, reason: str) -> None:
    """
    Mark an event handled without running its remaining consumers, so the
    transaction's later events can go. Records who skipped it and why.
    """
    if not reason.strip():
        raise ValueError("Skipping an event needs a reason.")
    LifecycleEvent.objects.filter(pk=event.pk, processed_at__isnull=True).update(
        processed_at=timezone.now(), skipped_by=by, skip_reason=reason.strip()
    )
    deliver_pending(event.transaction_id)
