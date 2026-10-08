import logging
from datetime import datetime, timedelta
from typing import Any

import sentry_sdk
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from notifications.models import Notification
from notifications.signals import notify

from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_items.models import Item
from borrowd_notifications.channels import (
    AppNotificationStrategy,
    EmailNotificationStrategy,
    NotificationPayload,
    NotificationStrategy,
    PUSHNotificationStrategy,
)
from borrowd_notifications.models import (
    ChannelType,
    ConversationNudge,
    NotificationMetadata,
    NotificationPreference,
    NotificationState,
    NotificationType,
)
from borrowd_users.models import BorrowdUser, Profile
from borrowd_users.system import get_system_user

logger = logging.getLogger(__name__)

_DEDUP_WINDOW = timedelta(minutes=10)
_EMAIL_HOURLY_LIMIT = 10
_SUMMARY_DIGEST_DELAY = timedelta(hours=1)
_RECENTLY_READ_WINDOW = timedelta(minutes=5)


class NotificationService:
    _backends: dict[ChannelType, type[NotificationStrategy]] = {
        ChannelType.APP: AppNotificationStrategy,
        ChannelType.EMAIL: EmailNotificationStrategy,
        ChannelType.PUSH: PUSHNotificationStrategy,
    }

    @classmethod
    def _get_backend(cls, channel: ChannelType) -> NotificationStrategy:
        try:
            backend_cls = cls._backends[channel]
        except KeyError:
            raise ValueError(f"Unknown notification backend: {channel}")
        return backend_cls()

    @staticmethod
    def _dispatched_channels(notification: Notification) -> set[str]:
        """Channels through witch this notification was sent."""
        if not isinstance(notification.data, dict):
            return set()
        return set(notification.data.get("channels", {}).keys())

    @staticmethod
    def _channel_results(notification: Notification) -> dict[str, Any]:
        """Channels and status for this notification."""
        if not isinstance(notification.data, dict):
            return {}
        result: dict[str, Any] = notification.data.get("channels", {})
        return result

    @classmethod
    def was_delivered(cls, notification: Notification) -> bool:
        """Whether any channel has reported success for this notification."""
        return any(
            isinstance(result, dict)
            and result.get("status") == NotificationState.SUCCESS.value
            for result in cls._channel_results(notification).values()
        )

    @staticmethod
    def _get_enabled_channels(
        user: BorrowdUser, notification_type: NotificationType
    ) -> set[ChannelType]:
        channels: set[ChannelType] = set()

        if notification_type in NotificationType.mandatory_types():
            channels.update({ChannelType.APP, ChannelType.EMAIL})

        pref, _ = NotificationPreference.objects.get_or_create(
            user=user,
            notification_type=notification_type.value,
            defaults={
                "in_app_enabled": True,
                "email_enabled": True,
                "push_enabled": False,
            },
        )

        if pref.in_app_enabled:
            channels.add(ChannelType.APP)
        if pref.email_enabled:
            channels.add(ChannelType.EMAIL)
        if pref.push_enabled:
            channels.add(ChannelType.PUSH)
        return channels

    @staticmethod
    def _is_duplicate(notification: Notification) -> bool:
        duplicate_exists: bool = (
            Notification.objects.filter(
                actor_content_type=notification.actor_content_type,
                actor_object_id=notification.actor_object_id,
                recipient=notification.recipient,
                verb=notification.verb,
                target_content_type=notification.target_content_type,
                target_object_id=notification.target_object_id,
                timestamp__gte=notification.timestamp - _DEDUP_WINDOW,
            )
            .filter(
                Q(timestamp__lt=notification.timestamp)
                | Q(timestamp=notification.timestamp, pk__lt=notification.pk)
            )
            .exists()
        )

        return duplicate_exists

    @staticmethod
    def _is_email_throttled(recipient: BorrowdUser) -> bool:
        return bool(
            Notification.objects.filter(
                recipient=recipient,
                emailed=True,
                timestamp__gte=timezone.now() - timedelta(hours=1),
            ).count()
            >= _EMAIL_HOURLY_LIMIT
        )

    @staticmethod
    def _schedule_summary_digest(recipient: BorrowdUser) -> dict[str, object]:
        return {
            "recipient_id": recipient.pk,
            "scheduled_for": (timezone.now() + _SUMMARY_DIGEST_DELAY).isoformat(),
            "status": NotificationState.PENDING.value,
        }

    @classmethod
    def send_notification(cls, notification: Notification) -> None:
        try:
            cls._dispatch(notification)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            logger.exception("Notification dispatch failed (pk=%s)", notification.pk)

    @staticmethod
    def _recently_read_the_conversation(notification: Notification) -> bool:
        """Whether the recipient read a message sent in the last few minutes."""
        since = timezone.now() - _RECENTLY_READ_WINDOW
        return bool(
            ConversationNudge.objects.filter(
                pk=notification.target_object_id,
                recipient_id=notification.recipient_id,
            )
            .filter(
                Q(
                    thread__lender_id=F("recipient_id"),
                    thread__lender_last_read_message__created_at__gte=since,
                )
                | Q(
                    thread__borrower_id=F("recipient_id"),
                    thread__borrower_last_read_message__created_at__gte=since,
                )
            )
            .exists()
        )

    @classmethod
    def _dispatch(cls, notification: Notification) -> None:
        if notification.actor == notification.recipient:
            return

        if cls._is_duplicate(notification):
            return

        try:
            notification_type = NotificationType(notification.verb)
        except ValueError:
            logger.warning("Unknown notification verb: %s", notification.verb)
            return

        channels = cls._get_enabled_channels(notification.recipient, notification_type)
        # Mid-conversation, the open page already shows each new message.
        if (
            notification_type is NotificationType.NEW_MESSAGE
            and ChannelType.EMAIL in channels
            and cls._recently_read_the_conversation(notification)
        ):
            channels.discard(ChannelType.EMAIL)
        summary_digest: dict[str, object] | None = None

        if ChannelType.EMAIL in channels and cls._is_email_throttled(
            notification.recipient
        ):
            channels.discard(ChannelType.EMAIL)
            summary_digest = cls._schedule_summary_digest(notification.recipient)

        if not channels:
            if summary_digest is not None:
                Notification.objects.filter(pk=notification.pk).update(
                    data={"summary_digest": summary_digest}
                )
            return

        payload = NotificationPayload.from_notification(notification, channels)

        for channel in channels:
            try:
                backend = cls._get_backend(channel)
                backend.send(payload)
            except Exception as exc:
                sentry_sdk.capture_exception(exc)
                payload.data._error(channel, str(exc))

        data = payload.data.to_dict()
        if summary_digest is not None:
            data["summary_digest"] = summary_digest

        update_kwargs: dict[str, Any] = {"data": data}
        email_result = payload.data.channels.get(ChannelType.EMAIL)
        if (
            email_result is not None
            and email_result.status == NotificationState.SUCCESS
        ):
            update_kwargs["emailed"] = True
        Notification.objects.filter(pk=notification.pk).update(**update_kwargs)

        app_result = payload.data.channels.get(ChannelType.APP)
        NotificationMetadata.objects.update_or_create(
            notification=notification,
            defaults={
                "visible_in_app": app_result is not None
                and app_result.status == NotificationState.SUCCESS
            },
        )

    @classmethod
    def send_join_group_nudge_if_needed(cls, item: Item) -> None:
        """Nudge a user to join a group the first time they add an item
        while belonging to no active group — otherwise they have no one to
        share it with and onboarding stalls. Shown at most once per user,
        regardless of how many items they add while still groupless.

        Called directly from `ItemCreateView.form_valid` (the "Add Item"
        flow) rather than wired as an Item post_save signal, so it fires only
        for a user's own deliberate item creation and not for every
        programmatic `Item.objects.create()` call (fixtures, other flows).
        """
        owner = item.owner
        # A fresh query rather than `owner.profile`'s cached OneToOne
        # descriptor: a caller that reuses the same in-memory user across
        # more than one item creation (e.g. a bulk-import loop) must see
        # this flag's latest value, not whatever was cached on first read.
        profile = Profile.objects.get(user=owner)
        if profile.join_group_nudge_sent:
            return

        has_active_membership = Membership.objects.filter(
            user=owner, status=MembershipStatus.ACTIVE
        ).exists()
        if has_active_membership:
            return

        notify.send(
            get_system_user(),
            recipient=[owner],
            verb=NotificationType.ITEM_ADDED_NEEDS_GROUP.value,
            action_object=item,
            target=item,
            description="Great job adding an item! Join a group to start sharing it.",
        )
        Profile.objects.filter(pk=profile.pk).update(join_group_nudge_sent=True)

    @classmethod
    def send_add_profile_photo_nudge_if_needed(cls, group: BorrowdGroup) -> None:
        """Nudge a user to add a profile photo the first time they create a
        group while having none — their photo is what helps fellow group
        members recognize them. Shown at most once per user, regardless of
        how many groups they create before adding one.

        Called directly from `GroupCreateView.form_valid` (the "Create
        Group" flow) rather than wired as a BorrowdGroup post_save signal,
        so it fires only for a user's own deliberate group creation and not
        for every programmatic `BorrowdGroup.objects.create_group()` call
        (fixtures, other flows).
        """
        creator = group.created_by
        profile = Profile.objects.get(user=creator)
        if profile.add_profile_photo_nudge_sent:
            return

        if profile.image:
            return

        notify.send(
            get_system_user(),
            recipient=[creator],
            verb=NotificationType.GROUP_CREATED_NEEDS_PHOTO.value,
            action_object=group,
            target=group,
            description="Great job creating a group! Add a photo to your profile.",
        )
        Profile.objects.filter(pk=profile.pk).update(add_profile_photo_nudge_sent=True)

    @classmethod
    def send_invite_friends_nudge_if_needed(cls, user: BorrowdUser) -> None:
        """Nudge a user to invite friends to their group the first time they
        add a profile photo — otherwise their group stays empty and
        onboarding stalls. Shown at most once per user, regardless of how
        many times they change their photo afterward.

        Called directly from `upload_profile_photo_view` (the "Add Photo"
        flow) rather than wired as a Profile post_save signal, so it fires
        only for a user's own deliberate photo upload and not for every
        programmatic `Profile` save (fixtures, other flows).
        """
        profile = Profile.objects.get(user=user)
        if profile.invite_friends_nudge_sent:
            return

        group = (
            BorrowdGroup.objects.filter(created_by=user, deleted_at__isnull=True)
            .order_by("created_at")
            .first()
        )
        if group is None:
            return

        notify.send(
            get_system_user(),
            recipient=[user],
            verb=NotificationType.PHOTO_ADDED_NEEDS_INVITES.value,
            action_object=group,
            target=group,
            description="Great job adding a photo! Now invite friends to join your group.",
        )
        Profile.objects.filter(pk=profile.pk).update(invite_friends_nudge_sent=True)

    @classmethod
    def send_pending_digests(cls) -> int:
        """Send summary digest emails for all due pending digests. Returns count sent."""
        now = timezone.now()

        # Notification.data is stored as serialised text (jsonfield library), so
        # nested ORM key lookups are not supported. Pre-filter by a known substring
        # then do precise Python-side checks for status and scheduled_for.
        pending = list(
            Notification.objects.filter(data__contains="summary_digest").select_related(
                "recipient"
            )
        )

        by_recipient: dict[int, tuple[BorrowdUser, list[Notification]]] = {}
        for notification in pending:
            if not isinstance(notification.data, dict):
                continue
            digest = notification.data.get("summary_digest", {})
            if digest.get("status") != NotificationState.PENDING.value:
                continue
            scheduled_for_str = digest.get("scheduled_for", "")
            if not scheduled_for_str:
                continue
            try:
                scheduled_for = datetime.fromisoformat(scheduled_for_str)
            except ValueError:
                continue
            if scheduled_for > now:
                continue
            recipient = notification.recipient
            if recipient.pk not in by_recipient:
                by_recipient[recipient.pk] = (recipient, [])
            by_recipient[recipient.pk][1].append(notification)

        for recipient, notifications in by_recipient.values():
            cls._send_digest_for_recipient(recipient, notifications)
        return len(by_recipient)

    @classmethod
    def _send_digest_for_recipient(
        cls, recipient: BorrowdUser, notifications: list[Notification]
    ) -> None:
        """Render and send a single summary digest email, then update statuses."""
        messages = []
        for notification in notifications:
            try:
                notification_type = NotificationType(notification.verb)
                context = NotificationType._get_template_context_for(notification)
                messages.append(notification_type.message_template.format(**context))
            except (ValueError, KeyError):
                messages.append(notification.description or str(notification.verb))

        email_context = {
            "recipient_name": recipient.first_name,
            "notification_messages": messages,
            "inbox_url": settings.BASE_URL + reverse("notification-inbox"),
        }

        try:
            text_body = render_to_string(
                "notifications/messages/summary_digest.txt", email_context
            )
            html_body = render_to_string(
                "notifications/messages/summary_digest.html", email_context
            )
            send_mail(
                subject="Notifications you missed on Borrow'd",
                message=text_body,
                html_message=html_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient.email],
                fail_silently=False,
            )
            new_status = NotificationState.SUCCESS.value
            logger.info(
                "Sent summary digest to %s (%d notifications)",
                recipient.email,
                len(notifications),
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            logger.error(
                "Failed to send summary digest to %s: %s", recipient.email, exc
            )
            new_status = NotificationState.ERROR.value

        for notification in notifications:
            data = (
                dict(notification.data) if isinstance(notification.data, dict) else {}
            )
            data["summary_digest"] = {
                **data.get("summary_digest", {}),
                "status": new_status,
            }
            Notification.objects.filter(pk=notification.pk).update(data=data)
