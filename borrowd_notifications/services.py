import logging
from datetime import datetime, timedelta
from typing import Any, Type

import sentry_sdk
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from notifications.models import Notification

from borrowd_notifications.channels import (
    AppNotificationStrategy,
    EmailNotificationStrategy,
    NotificationPayload,
    NotificationStrategy,
    PUSHNotificationStrategy,
)
from borrowd_notifications.models import (
    ChannelType,
    NotificationMetadata,
    NotificationPreference,
    NotificationState,
    NotificationType,
)
from borrowd_users.models import BorrowdUser

logger = logging.getLogger(__name__)

_DEDUP_WINDOW = timedelta(minutes=10)
_EMAIL_HOURLY_LIMIT = 10
_SUMMARY_DIGEST_DELAY = timedelta(hours=1)


class NotificationService:
    _backends: dict[ChannelType, Type[NotificationStrategy]] = {
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

    @staticmethod
    def _get_enabled_channels(
        user: BorrowdUser, notification_type: NotificationType
    ) -> set[ChannelType]:
        channels: set[ChannelType] = set()

        if notification_type in NotificationType.mandatory_types():
            channels.update({ChannelType.APP, ChannelType.EMAIL})

        try:
            pref = NotificationPreference.objects.get(
                user=user, notification_type=notification_type.value
            )
        except NotificationPreference.DoesNotExist:
            NotificationPreference.objects.create(
                user=user,
                notification_type=notification_type.value,
                defaults={
                    "in_app_enabled": True,
                    "email_enabled": True,
                    "push_enabled": False,
                },
            )
            return {ChannelType.APP, ChannelType.EMAIL}

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
