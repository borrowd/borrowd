from __future__ import annotations

from allauth.account.models import EmailAddress
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from notifications.signals import notify

from borrowd_groups.models import Membership, MembershipStatus
from borrowd_items.models import (
    AvailabilitySubscription,
    AvailabilitySubscriptionStatus,
    Item,
    ItemStatus,
    Transaction,
    TransactionStatus,
)
from borrowd_notifications.models import NotificationType

from .exceptions import AccountDeletionBlocked
from .models import BorrowdUser

# Pre-collection transactions: nothing has changed hands, so these are simply
# cancelled on deletion (and the counterparty's item freed).
_OPEN_TRANSACTION_STATUSES = (
    TransactionStatus.REQUESTED,
    TransactionStatus.ACCEPTED,
)

# A borrower is physically on the hook for an item once collection starts and
# stays so until the lender confirms the return. Deletion is blocked while a
# leaving borrower holds any of these: you can't vanish with someone's property,
# and an asserted-but-unconfirmed return isn't proof the item actually came back.
# When the *owner* leaves mid-loan these are left open instead. The borrower
# closes the loan out themselves (see _notify_borrowers_of_in_flight_lends).
_ITEM_IN_HAND_STATUSES = (
    TransactionStatus.COLLECTION_ASSERTED,
    TransactionStatus.COLLECTED,
    TransactionStatus.RETURN_ASSERTED,
)


def soft_delete_account(user: BorrowdUser, *, deleted_by: BorrowdUser) -> None:
    """
    Soft-delete and anonymize `user`.

    Raises `AccountDeletionBlocked` while the user is still holding a borrowed
    item (collection started, return not yet confirmed): they must finish
    returning it first. Lending is allowed. Owned items are soft-deleted, and
    any loans still out are left open so the borrower can close them out and
    arrange the item's return with the (departed) owner directly.

    Everything else: open requests are cancelled,
    photos are wiped from storage, group memberships are dropped (reusing the
    leave-group moderator handoff), and the user is stripped of identifying
    data, deactivated, and dropped from any sessions.
    """
    if Transaction.objects.filter(
        party2=user, status__in=_ITEM_IN_HAND_STATUSES
    ).exists():
        raise AccountDeletionBlocked(
            "You're still holding borrowed items. Return them and wait for the "
            "owner to confirm before deleting your account."
        )

    with transaction.atomic():
        _cancel_open_transactions(user, deleted_by)
        _notify_borrowers_of_in_flight_lends(user)
        _cancel_availability_subscriptions(user)
        _soft_delete_owned_items(user, deleted_by)
        _destroy_profile_photo_and_clear_bio(user, deleted_by)
        _remove_group_memberships(user)
        _soft_delete_and_anonymize_user(user, deleted_by)


def _cancel_open_transactions(user: BorrowdUser, deleted_by: BorrowdUser) -> None:
    """Cancel pre-collection requests and notify the other party."""
    open_transactions = Transaction.objects.filter(
        Q(party1=user) | Q(party2=user),
        status__in=_OPEN_TRANSACTION_STATUSES,
    ).select_related("item", "item__owner", "party1", "party2")

    for txn in open_transactions:
        item = txn.item
        # Free the counterparty's item back up. The leaving user's own items are
        # about to be soft-deleted, so there's no point flipping their status.
        if item.owner != user:
            item.status = ItemStatus.AVAILABLE
            item.save()

        txn.status = TransactionStatus.CANCELLED
        txn.updated_by = deleted_by
        txn.save()

        _notify_counterparty_of_cancellation(txn, user)


def _notify_counterparty_of_cancellation(
    txn: Transaction, leaving_user: BorrowdUser
) -> None:
    """
    Tell the other party their open request was cancelled by the account
    closure. The message differs by who left: when the borrower (party2) leaves,
    the owner's item is freed, but when the owner (party1) leaves, the item is
    gone.
    """
    if txn.party2 == leaving_user:
        # Borrower left; tell the owner their item is free again.
        counterparty = txn.party1
        verb = NotificationType.REQUEST_CANCELLED_BORROWER_LEFT
        description = (
            "A request for your item was cancelled "
            "because the borrower closed their account"
        )
    else:
        # Owner left; tell the borrower the item is no longer available.
        counterparty = txn.party2
        verb = NotificationType.REQUEST_CANCELLED_OWNER_LEFT
        description = (
            "Your Borrow'd request was cancelled "
            "because the item owner closed their account"
        )

    notify.send(
        leaving_user,
        recipient=[counterparty],
        verb=verb.value,
        action_object=txn.item,
        target=txn,
        description=description,
    )


def _notify_borrowers_of_in_flight_lends(user: BorrowdUser) -> None:
    """
    When the leaving user is an owner with items still out on loan, leave those
    loans open so the borrower closes them out themselves via the
    counterparty-gone action, but tell each borrower what happened via notification.
    """
    in_flight_lends = Transaction.objects.filter(
        party1=user,
        status__in=_ITEM_IN_HAND_STATUSES,
    ).select_related("item", "party2")

    for txn in in_flight_lends:
        notify.send(
            user,
            recipient=[txn.party2],
            verb=NotificationType.LOAN_ENDED_OWNER_LEFT.value,
            action_object=txn.item,
            target=txn,
            description="The owner of an item you borrowed closed their account",
        )


def _cancel_availability_subscriptions(user: BorrowdUser) -> None:
    """
    Cancel the user's own active "notify when available" subscriptions and any
    that other members hold on the user's (soon-gone) items.
    """
    subscriptions = AvailabilitySubscription.objects.filter(
        Q(user=user) | Q(item__owner=user),
        status=AvailabilitySubscriptionStatus.ACTIVE,
    )
    for subscription in subscriptions:
        subscription.cancel_subscription()


def _soft_delete_owned_items(user: BorrowdUser, deleted_by: BorrowdUser) -> None:
    """
    Soft-delete owned items and permanently destroy their photos from storage.
    """
    for item in Item.objects.filter(owner=user):
        _destroy_item_photos(item)
        item.soft_delete(deleted_by)


def _destroy_item_photos(item: Item) -> None:
    """
    Hard-delete an item's photo rows. django-cleanup deletes each backing file
    from storage on row delete
    See: https://github.com/un1t/django-cleanup
    """
    for photo in item.photos.all():
        photo.delete()


def _destroy_profile_photo_and_clear_bio(
    user: BorrowdUser, deleted_by: BorrowdUser
) -> None:
    """
    Clear the user's profile photo and bio.
    See: https://github.com/un1t/django-cleanup
    """

    profile = user.profile
    profile.image = None
    profile.bio = ""
    profile.updated_by = deleted_by
    profile.save()


def _remove_group_memberships(user: BorrowdUser) -> None:
    """
    Hard-delete every group membership row. Reuses `remove_user` with the
    leave-group bypass so a departing sole moderator triggers the existing
    "needs a new moderator" handoff notification instead of being blocked.
    Groups left with no active members are hard-deleted
    """
    memberships = list(Membership.objects.filter(user=user).select_related("group"))
    for membership in memberships:
        group = membership.group
        group.remove_user(user, bypass_last_moderator_check=True)

        remaining_active_members = Membership.objects.filter(
            group=group,
            status=MembershipStatus.ACTIVE,
        ).exists()
        if not remaining_active_members:
            group.delete()


def _soft_delete_and_anonymize_user(user: BorrowdUser, deleted_by: BorrowdUser) -> None:
    """
    Soft-delete the user row while stripping identifying data, deactivating
    login, and invalidating every session.

    Setting an unusable password rotates the session auth hash, which Django
    re-checks on every request. So all existing
    sessions are invalidated and stale cookies resolve to an anonymous user
    (login redirect) rather than a 500.
    See: https://docs.djangoproject.com/en/5.2/topics/auth/default/#session-invalidation-on-password-change
    """
    user.first_name = "Deleted"
    user.last_name = "User"
    user.username = f"deleted_{user.pk}"
    user.email = f"deleted_{user.pk}@borrowd.org"
    user.is_active = False
    user.deleted_at = timezone.now()
    user.deleted_by = deleted_by
    user.set_unusable_password()
    user.save()

    # Delete stored allauth email address so the old address can't be
    # used for login-by-code and isn't retained after anonymization.
    EmailAddress.objects.filter(user=user).delete()
