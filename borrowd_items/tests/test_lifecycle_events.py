"""Every status change leaves an event, and every event is delivered once."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock
from typing import Any
from unittest import mock, skipUnless
from uuid import uuid4

from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from borrowd_items import events
from borrowd_items.commands import ItemCommand, run_item_command
from borrowd_items.models import (
    Item,
    ItemAction,
    LifecycleEvent,
    LifecycleEventConsumption,
    ResolutionReason,
    Transaction,
    TransactionStatus,
)
from borrowd_items.tests.test_item_lifecycle_writes import (
    EXPECTED_WRITES,
    LENDER,
    rolled_back,
)
from borrowd_users.models import BorrowdUser
from borrowd_users.services import soft_delete_account
from borrowd_users.system import SYSTEM_USER_USERNAME

Handler = Callable[[LifecycleEvent], None]


def consumers(**handlers: Handler) -> "mock._patch_dict":
    """Swap in these consumers for the duration of a test."""
    return mock.patch.dict(events._consumers, handlers, clear=True)


class EventTestCase(TestCase):
    lender: BorrowdUser
    borrower: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.lender, cls.borrower = (
            BorrowdUser.objects.create_user(
                username=name, email=f"{name}@example.com", password="password"
            )
            for name in ("ev_lender", "ev_borrower")
        )

    def make_item(self) -> Item:
        return Item.objects.create(
            name="Drill",
            description="A drill",
            owner=self.lender,
            created_by=self.lender,
            updated_by=self.lender,
        )

    def requested_item(self) -> tuple[Item, Transaction]:
        item = self.make_item()
        item.process_action(self.borrower, ItemAction.REQUEST_ITEM)
        return item, Transaction.objects.get(item=item)

    def events_for(self, tx: Transaction) -> list[LifecycleEvent]:
        return list(LifecycleEvent.objects.filter(transaction=tx).order_by("revision"))


class RecordingTests(EventTestCase):
    def test_every_action_records_one_event(self) -> None:
        for write in EXPECTED_WRITES:
            name = f"{write.source.name} + {write.action} by {write.actor}"
            with self.subTest(name), rolled_back():
                actor = self.lender if write.actor == LENDER else self.borrower
                item = self.make_item()
                tx = Transaction.objects.create(
                    item=item,
                    party1=self.lender,
                    party2=self.borrower,
                    status=write.source,
                    created_by=self.lender,
                    updated_by=(
                        self.lender if write.updated_by == LENDER else self.borrower
                    ),
                    return_requested_at=(
                        timezone.now() - timedelta(days=write.return_requested_days_ago)
                        if write.return_requested_days_ago is not None
                        else None
                    ),
                )

                item.process_action(actor, write.action)

                (event,) = self.events_for(tx)
                self.assertEqual(event.source_status, write.source)
                self.assertEqual(event.target_status, write.transaction_status_after)
                self.assertEqual(event.action, write.action)
                self.assertEqual(event.actor_id, actor.pk)
                self.assertEqual(
                    event.revision, Item.all_objects.get(pk=item.pk).revision
                )

    def test_a_request_records_the_event_that_opens_the_transaction(self) -> None:
        item = self.make_item()
        key = uuid4()
        result = run_item_command(
            ItemCommand(
                actor=self.borrower,
                action=ItemAction.REQUEST_ITEM,
                item_id=item.pk,
                key=key,
            )
        )

        (event,) = LifecycleEvent.objects.filter(
            transaction=Transaction.objects.get(item=item)
        )
        self.assertIsNone(event.source_status)
        self.assertEqual(event.target_status, TransactionStatus.REQUESTED)
        self.assertEqual(event.action, ItemAction.REQUEST_ITEM)
        self.assertEqual(event.command_key, key)
        self.assertEqual(event.revision, result.revision)

    def test_a_forced_resolution_records_one(self) -> None:
        _, tx = self.requested_item()
        tx.force_resolve(
            resolved_by=self.lender, reason=ResolutionReason.MODERATOR_OVERRIDE
        )

        event = self.events_for(tx)[-1]
        self.assertEqual(event.source_status, TransactionStatus.REQUESTED)
        self.assertEqual(event.target_status, TransactionStatus.RESOLVED)
        self.assertEqual(event.action, "")
        self.assertEqual(event.actor_id, self.lender.pk)

    def test_closing_an_account_records_each_cancellation(self) -> None:
        _, tx = self.requested_item()
        soft_delete_account(self.borrower, deleted_by=self.borrower)

        event = self.events_for(tx)[-1]
        self.assertEqual(event.source_status, TransactionStatus.REQUESTED)
        self.assertEqual(event.target_status, TransactionStatus.CANCELLED)
        self.assertEqual(event.actor_id, self.borrower.pk)

    def test_a_transactions_events_come_in_revision_order(self) -> None:
        item, tx = self.requested_item()
        item.process_action(self.lender, ItemAction.ACCEPT_REQUEST)
        item.process_action(self.borrower, ItemAction.CANCEL_REQUEST)

        recorded = self.events_for(tx)
        self.assertEqual(
            [event.target_status for event in recorded],
            [
                TransactionStatus.REQUESTED,
                TransactionStatus.ACCEPTED,
                TransactionStatus.CANCELLED,
            ],
        )
        revisions = [event.revision for event in recorded]
        self.assertEqual(revisions, sorted(set(revisions)))


class DeliveryTests(EventTestCase):
    def setUp(self) -> None:
        self.seen: list[LifecycleEvent] = []

    def record(self, event: LifecycleEvent) -> None:
        self.seen.append(event)

    def test_an_event_is_delivered_once_its_change_commits(self) -> None:
        item = self.make_item()
        with consumers(record=self.record):
            with self.captureOnCommitCallbacks(execute=True):
                item.process_action(self.borrower, ItemAction.REQUEST_ITEM)

        (event,) = LifecycleEvent.objects.all()
        self.assertEqual(self.seen, [event])
        self.assertIsNotNone(event.processed_at)
        self.assertTrue(
            LifecycleEventConsumption.objects.filter(
                consumer="record", event=event
            ).exists()
        )

    def test_an_event_a_crash_left_behind_goes_out_with_the_sweeper(self) -> None:
        # Outside captureOnCommitCallbacks nothing runs after commit, which is
        # what a process dying right after the commit looks like.
        self.requested_item()
        with consumers(record=self.record):
            self.assertEqual(events.deliver_due(), 1)

        self.assertEqual(len(self.seen), 1)

    def test_delivering_again_does_not_run_a_consumer_twice(self) -> None:
        _, tx = self.requested_item()
        with consumers(record=self.record):
            events.deliver_pending(tx.pk)
            events.deliver_pending(tx.pk)
            events.deliver_due()

        self.assertEqual(len(self.seen), 1)

    def test_a_retry_only_reruns_the_consumer_that_failed(self) -> None:
        _, tx = self.requested_item()
        calls: list[str] = []
        failing = mock.Mock(side_effect=RuntimeError("down"))

        with (
            consumers(ok=lambda event: calls.append("ok"), flaky=failing),
            self.assertLogs("borrowd.items.events", level="WARNING"),
        ):
            events.deliver_pending(tx.pk)
            failing.side_effect = None
            later = timezone.now() + timedelta(hours=1)
            events.deliver_pending(tx.pk, now=later)

        self.assertEqual(calls, ["ok"])
        self.assertEqual(failing.call_count, 2)
        self.assertIsNotNone(LifecycleEvent.objects.get().processed_at)

    def test_a_failure_holds_back_only_its_own_transactions_later_events(
        self,
    ) -> None:
        stuck_item, stuck = self.requested_item()
        stuck_item.process_action(self.lender, ItemAction.ACCEPT_REQUEST)
        _, other = self.requested_item()
        first = self.events_for(stuck)[0]

        def fail_on_first(event: LifecycleEvent) -> None:
            if event.pk == first.pk:
                raise RuntimeError("down")
            self.seen.append(event)

        with (
            consumers(picky=fail_on_first),
            self.assertLogs("borrowd.items.events", level="WARNING"),
        ):
            events.deliver_due()

        self.assertEqual([event.transaction_id for event in self.seen], [other.pk])
        self.assertTrue(
            all(event.processed_at is None for event in self.events_for(stuck))
        )

    def test_retries_back_off_then_park_and_report(self) -> None:
        _, tx = self.requested_item()
        now = timezone.now()
        with (
            consumers(broken=mock.Mock(side_effect=RuntimeError("down"))),
            mock.patch("borrowd_items.events.sentry_sdk.capture_message") as report,
            self.assertLogs("borrowd.items.events", level="WARNING") as logs,
        ):
            for _ in range(events.MAX_ATTEMPTS):
                events.deliver_pending(tx.pk, now=now)
                event = LifecycleEvent.objects.get()
                if event.failed_at is None:
                    self.assertGreater(event.next_attempt_at, now)
                now = event.next_attempt_at

        event = LifecycleEvent.objects.get()
        self.assertEqual(event.attempts, events.MAX_ATTEMPTS)
        self.assertIsNotNone(event.failed_at)
        self.assertIn("down", event.last_error)
        report.assert_called_once()
        self.assertEqual(len(logs.records), events.MAX_ATTEMPTS)

    def test_a_replay_puts_a_parked_event_back_and_delivers_it(self) -> None:
        _, tx = self.requested_item()
        LifecycleEvent.objects.update(
            failed_at=timezone.now(), attempts=events.MAX_ATTEMPTS
        )

        with consumers(record=self.record):
            events.replay(LifecycleEvent.objects.get())

        event = LifecycleEvent.objects.get()
        self.assertIsNotNone(event.processed_at)
        self.assertEqual(len(self.seen), 1)

    def test_a_skip_says_who_and_why_and_lets_later_events_go(self) -> None:
        item, tx = self.requested_item()
        item.process_action(self.lender, ItemAction.ACCEPT_REQUEST)
        first, second = self.events_for(tx)
        LifecycleEvent.objects.filter(pk=first.pk).update(failed_at=timezone.now())

        with consumers(record=self.record):
            events.skip(first, by=self.lender, reason="Notified them by hand")

        first.refresh_from_db()
        self.assertEqual(first.skipped_by_id, self.lender.pk)
        self.assertEqual(first.skip_reason, "Notified them by hand")
        self.assertEqual(self.seen, [second])
        with self.assertRaises(ValueError):
            events.skip(second, by=self.lender, reason=" ")

    def test_the_sweeper_reports_events_waiting_too_long(self) -> None:
        self.requested_item()
        LifecycleEvent.objects.update(
            occurred_at=timezone.now() - timedelta(minutes=20),
            next_attempt_at=timezone.now() + timedelta(minutes=5),
        )
        with mock.patch("borrowd_items.events.sentry_sdk.capture_message") as report:
            events.deliver_due()
        report.assert_called_once()


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks.")
class ConcurrentDeliveryTests(TransactionTestCase):
    def test_two_dispatchers_deliver_each_event_once_and_in_order(self) -> None:
        # TransactionTestCase truncates migration data, so make the system user here.
        BorrowdUser.objects.get_or_create(username=SYSTEM_USER_USERNAME)
        lender = BorrowdUser.objects.create_user(username="ev_race_lender")
        borrower = BorrowdUser.objects.create_user(username="ev_race_borrower")
        item = Item.objects.create(
            name="Drill",
            description="A drill",
            owner=lender,
            created_by=lender,
            updated_by=lender,
        )
        with consumers():
            # Delivered with nobody listening, so only the new events below wait.
            item.process_action(borrower, ItemAction.REQUEST_ITEM)
        tx = Transaction.objects.get(item=item)
        waiting = [
            LifecycleEvent.objects.create(
                item=item,
                transaction=tx,
                revision=1000 + n,
                target_status=TransactionStatus.REQUESTED,
                actor=borrower,
            )
            for n in range(5)
        ]
        handled: list[Any] = []
        lock = Lock()

        def record(event: LifecycleEvent) -> None:
            with lock:
                handled.append(event.pk)

        def dispatch() -> int:
            close_old_connections()
            try:
                return events.deliver_pending(tx.pk)
            finally:
                connections.close_all()

        with consumers(record=record):
            with ThreadPoolExecutor(max_workers=2) as executor:
                delivered = [
                    future.result(timeout=20)
                    for future in [executor.submit(dispatch) for _ in range(2)]
                ]

        self.assertEqual(sum(delivered), len(waiting))
        self.assertEqual(handled, [event.pk for event in waiting])
