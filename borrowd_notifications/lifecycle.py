"""
Notifications about lifecycle changes, sent from the lifecycle events that
borrowd_items records with every status change (see borrowd_items.events).
They run after the change commits and are retried if they fail.
"""

from django.utils import timezone
from notifications.signals import notify

from borrowd_items import events
from borrowd_items.models import (
    AvailabilitySubscription,
    AvailabilitySubscriptionStatus,
    Item,
    LifecycleEvent,
    Transaction,
    TransactionStatus,
)
from borrowd_users.models import BorrowdUser

from .models import NotificationType

# A transaction ending in one of these may free its item for subscribers.
_FREES_THE_ITEM = (
    TransactionStatus.REJECTED,
    TransactionStatus.RETURNED,
    TransactionStatus.CANCELLED,
)


@events.consumer("notifications")
def notify_about_transition(event: LifecycleEvent) -> None:
    tx = Transaction.objects.select_related("item", "party1", "party2").get(
        pk=event.transaction_id
    )
    source = (
        TransactionStatus(event.source_status)
        if event.source_status is not None
        else None
    )
    target = TransactionStatus(event.target_status)
    _notify_parties(tx, source, target, event.actor)
    if target in _FREES_THE_ITEM:
        _notify_subscribers_if_available(tx.item)


def _notify_parties(
    tx: Transaction,
    source: TransactionStatus | None,
    target: TransactionStatus,
    actor: BorrowdUser,
) -> None:
    # A declined giveaway reverts to COLLECTED, which would otherwise fire the
    # collection-confirmed notification. Catch that transition first.
    if (
        source == TransactionStatus.GIVEAWAY_OFFERED
        and target == TransactionStatus.COLLECTED
    ):
        notify.send(
            tx.party2,
            recipient=[tx.party1],
            verb=NotificationType.GIVEAWAY_DECLINED.value,
            action_object=tx.item,
            target=tx,
            description=f"{tx.party2.first_name} declined your giveaway offer for {tx.item.name}",
        )
        return

    match target:
        case TransactionStatus.REQUESTED:
            notify.send(
                tx.party2,
                recipient=[tx.party1],
                verb=NotificationType.ITEM_REQUESTED.value,
                action_object=tx.item,
                target=tx,
                description=f"Someone's hoping to borrow your {tx.item.name}",
            )
        case TransactionStatus.ACCEPTED:
            notify.send(
                tx.party1,
                recipient=[tx.party2],
                verb=NotificationType.ITEM_REQUEST_ACCEPTED.value,
                action_object=tx.item,
                target=tx,
                description=f"Your request to borrow {tx.item.name} was approved",
            )
        case TransactionStatus.REJECTED:
            verb = (
                NotificationType.GIVEAWAY_REQUEST_DECLINED
                if source == TransactionStatus.GIVEAWAY_REQUESTED
                else NotificationType.ITEM_REQUEST_DENIED
            )
            notify.send(
                tx.party1,
                recipient=[tx.party2],
                verb=verb.value,
                action_object=tx.item,
                target=tx,
                description=f"Your request for {tx.item.name} was declined",
            )
        case TransactionStatus.COLLECTION_ASSERTED:
            who = "they've" if tx.item.owner != actor else "you've"
            notify.send(
                actor,
                recipient=[tx.counter_party(actor)],
                verb=NotificationType.COLLECTION_ASSERTED.value,
                action_object=tx.item,
                target=tx,
                description=f"{actor.first_name} says {who} collected {tx.item.name}. Please confirm.",
            )
        case TransactionStatus.COLLECTED:
            notify.send(
                actor,
                recipient=[tx.counter_party(actor)],
                verb=NotificationType.COLLECTION_CONFIRMED.value,
                action_object=tx.item,
                target=tx,
                description=f"The collection of {tx.item.name} has been confirmed!",
            )
        case TransactionStatus.GIVEAWAY_OFFERED:
            notify.send(
                tx.party1,
                recipient=[tx.party2],
                verb=NotificationType.GIVEAWAY_OFFER_SENT.value,
                action_object=tx.item,
                target=tx,
                description=f"{tx.party1.first_name} wants to give you {tx.item.name}!",
            )
        case TransactionStatus.GIVEAWAY_REQUESTED:
            notify.send(
                tx.party2,
                recipient=[tx.party1],
                verb=NotificationType.GIVEAWAY_REQUEST_RECEIVED.value,
                action_object=tx.item,
                target=tx,
                description=f"{tx.party2.first_name} would like your {tx.item.name}!",
            )
        case TransactionStatus.OWNERSHIP_TRANSFERRED:
            if source == TransactionStatus.GIVEAWAY_REQUESTED:
                notify.send(
                    tx.party1,
                    recipient=[tx.party2],
                    verb=NotificationType.GIVEAWAY_REQUEST_APPROVED.value,
                    action_object=tx.item,
                    target=tx,
                    description=f"{tx.party1.first_name} approved your request - {tx.item.name} is yours!",
                )
                notify.send(
                    tx.party1,
                    recipient=[tx.party1],
                    verb=NotificationType.GIVEAWAY_COMPLETED.value,
                    action_object=tx.item,
                    target=tx,
                    description=f"You gave {tx.item.name} to {tx.party2.first_name}",
                )
                return
            notify.send(
                tx.party2,
                recipient=[tx.party1],
                verb=NotificationType.GIVEAWAY_ACCEPTED.value,
                action_object=tx.item,
                target=tx,
                description=f"{tx.party2.first_name} accepted your gift of {tx.item.name}",
            )
        case TransactionStatus.RETURN_ASSERTED:
            notify.send(
                actor,
                recipient=[tx.counter_party(actor)],
                verb=NotificationType.RETURN_ASSERTED.value,
                action_object=tx.item,
                target=tx,
                description=f"{actor.first_name} says {tx.item.name} has been returned. Please confirm.",
            )
        case TransactionStatus.RETURNED:
            notify.send(
                actor,
                recipient=[tx.counter_party(actor)],
                verb=NotificationType.RETURN_CONFIRMED.value,
                action_object=tx.item,
                target=tx,
                description=f"{tx.item.name} return confirmed. Thanks for borrowing!",
            )
        case TransactionStatus.RETURN_REQUESTED:
            notify.send(
                tx.party1,
                recipient=[tx.party2],
                verb=NotificationType.ITEM_RETURN_REQUESTED.value,
                action_object=tx.item,
                target=tx,
                description="Return requested",
            )
        case TransactionStatus.DISPUTED:
            # The party who raised the dispute notifies the other one.
            if tx.dispute_raised_by is None:
                return
            notified_party = (
                tx.party1 if tx.dispute_raised_by == tx.party2 else tx.party2
            )
            notify.send(
                tx.dispute_raised_by,
                recipient=[notified_party],
                verb=NotificationType.ITEM_DISPUTED.value,
                action_object=tx.item,
                target=tx,
                description="A dispute has been raised",
            )


def _notify_subscribers_if_available(item: Item) -> None:
    """
    Check if the item is borrowable and notify subscribers.
    """
    item.refresh_from_db()  # Ensure we have the latest data

    if item.is_borrowable():
        subscriptions = AvailabilitySubscription.get_active_subscriptions_for_item(item)
        for subscription in subscriptions:
            notify.send(
                item.owner,
                recipient=[subscription.user],
                verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
                action_object=item,
                target=subscription,
                description=f"{item.name} is now available",
            )

            AvailabilitySubscription.objects.filter(
                pk=subscription.pk,
                status=AvailabilitySubscriptionStatus.ACTIVE,
                notified_at__isnull=True,
            ).update(
                notified_at=timezone.now(),
                status=AvailabilitySubscriptionStatus.NOTIFIED,
            )
