"""
This module contains signals for handling creating notifications and emailing notifications.

Signal handlers for created app models (e.g. Membership) will trigger a notify.send()
call which will create a Notification object for each user in the recipient list.
Transaction notifications come from lifecycle events instead; see lifecycle.py. A separate signal handler
send_notification() will catch Notification objects post-save, send emails based on Notification attributes,
and fill in the reserved "emailed" field.

To add a new Notification:
    - follow the notification-type checklist in model.py
    - add/update the appropriate signal and call notify.send()

django-notifications repo: https://github.com/django-notifications/django-notifications
"""

from typing import Any, cast

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from notifications.models import Notification
from notifications.signals import notify

from borrowd_community_requests.models import CommunityRequest, CommunityRequestResponse
from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_items.models import (
    AvailabilitySubscription,
    AvailabilitySubscriptionStatus,
    Item,
)
from borrowd_users.models import BorrowdUser

from .models import NotificationMetadata, NotificationType
from .services import NotificationService


@receiver(post_save, sender=Notification)
def send_notification(
    sender: type[Notification], instance: Notification, created: bool, **kwargs: Any
) -> None:
    """
    Delegates to the service layer to handle notification preferences and channel dispatch.
    """

    if not created:
        return

    NotificationMetadata.objects.create(notification=instance)
    Notification.objects.filter(pk=instance.pk).update(public=False)
    transaction.on_commit(
        lambda: NotificationService.send_notification(instance), robust=True
    )


@receiver(pre_save, sender=Membership)
def capture_membership_previous_status(
    sender: type[Membership], instance: Membership, **kwargs: Any
) -> None:
    """Store the pre-save status on the instance so post_save can detect transitions."""
    if instance.pk:
        try:
            instance._previous_status = Membership.objects.values_list(
                "status", flat=True
            ).get(pk=instance.pk)
        except Membership.DoesNotExist:
            instance._previous_status = None
    else:
        instance._previous_status = None


@receiver(post_save, sender=Membership)
def send_membership_notifications(
    sender: type[Membership], instance: Membership, created: bool, **kwargs: Any
) -> None:
    """Send notifications for membership lifecycle events."""
    if created:
        if instance.status == MembershipStatus.PENDING:
            moderators = [
                m.user
                for m in Membership.objects.filter(
                    group=instance.group,
                    is_moderator=True,
                    status=MembershipStatus.ACTIVE,
                ).select_related("user")
            ]
            if moderators:
                notify.send(
                    instance.user,
                    recipient=moderators,
                    verb=NotificationType.MEMBERSHIP_PENDING.value,
                    action_object=instance,
                    target=instance.group,
                    description=f"{instance.user.first_name} wants to join {instance.group.name}. Review their request.",
                )
        elif instance.status == MembershipStatus.ACTIVE:
            active_members = BorrowdUser.objects.filter(
                membership__group=instance.group,
                membership__status=MembershipStatus.ACTIVE,
            ).exclude(pk=instance.user.pk)
            notify.send(
                instance.user,
                recipient=active_members,
                verb=NotificationType.GROUP_MEMBER_JOINED.value,
                action_object=instance,
                target=instance.group,
                description=f"{instance.user.first_name} just joined {instance.group.name}",
            )
    else:
        previous_status = getattr(instance, "_previous_status", None)
        if (
            instance.status == MembershipStatus.ACTIVE
            and previous_status == MembershipStatus.PENDING
        ):
            notify.send(
                instance.group,
                recipient=[instance.user],
                verb=NotificationType.MEMBERSHIP_APPROVED.value,
                action_object=instance,
                target=instance.group,
                description=f"You've been approved to join {instance.group.name}!",
            )
            active_members = BorrowdUser.objects.filter(
                membership__group=instance.group,
                membership__status=MembershipStatus.ACTIVE,
            ).exclude(pk=instance.user.pk)
            notify.send(
                instance.user,
                recipient=active_members,
                verb=NotificationType.GROUP_MEMBER_JOINED.value,
                action_object=instance,
                target=instance.group,
                description=f"{instance.user.first_name} just joined {instance.group.name}",
            )


@receiver(post_save, sender=AvailabilitySubscription)
def send_item_available_notification_on_subscription(
    sender: type[AvailabilitySubscription],
    instance: AvailabilitySubscription,
    created: bool,
    **kwargs: str,
) -> None:
    """
    Send notifications when an availability subscription is created for an item that is not available.
    """

    item = cast(Item | None, instance.item)
    if (
        created
        and instance.status == AvailabilitySubscriptionStatus.ACTIVE
        and item is not None
        and not item.is_borrowable()
    ):
        notify.send(
            instance.item,
            recipient=[instance.user],
            verb=NotificationType.ITEM_SUBSCRIPTION.value,
            action_object=item,
            target=instance,
            description=f"You have subscribed to be notified when {item.name} becomes available. We will let you know when it does!",
        )


def _send_community_request_posted_notifications(instance: CommunityRequest) -> None:
    """One notification per group the requester shares with other active
    members — a user sharing two groups with the requester gets two
    notifications, mirroring GROUP_MEMBER_JOINED's fan-out.
    """
    requester_group_ids = Membership.objects.filter(
        user=instance.requester,
        status=MembershipStatus.ACTIVE,
    ).values_list("group_id", flat=True)

    for group in BorrowdGroup.objects.filter(pk__in=requester_group_ids):
        other_active_members = BorrowdUser.objects.filter(
            membership__group=group,
            membership__status=MembershipStatus.ACTIVE,
        ).exclude(pk=instance.requester_id)
        notify.send(
            instance.requester,
            recipient=other_active_members,
            verb=NotificationType.COMMUNITY_REQUEST_POSTED.value,
            action_object=instance,
            target=group,
            description=f"{instance.requester.first_name} is looking for {instance.item_name}",
        )


@receiver(post_save, sender=CommunityRequest)
def send_community_request_posted_notification(
    sender: type[CommunityRequest],
    instance: CommunityRequest,
    created: bool,
    **kwargs: Any,
) -> None:
    """Send COMMUNITY_REQUEST_POSTED when a new request is created."""
    if created:
        _send_community_request_posted_notifications(instance)


@receiver(post_save, sender=CommunityRequestResponse)
def send_community_request_fulfilled_notification(
    sender: type[CommunityRequestResponse],
    instance: CommunityRequestResponse,
    created: bool,
    **kwargs: Any,
) -> None:
    """Send COMMUNITY_REQUEST_FULFILLED when a lender responds. A freshly
    inserted response row is always a genuine, one-shot event — unlike
    CommunityRequest's own saves (e.g. cancel()), there's no unrelated-save
    ambiguity to guard against here.
    """
    if not created:
        return

    notify.send(
        instance.item.owner,
        recipient=[instance.request.requester],
        verb=NotificationType.COMMUNITY_REQUEST_FULFILLED.value,
        action_object=instance.item,
        target=instance.request,
        description=f"Someone responded to your request for {instance.request.item_name}",
    )
