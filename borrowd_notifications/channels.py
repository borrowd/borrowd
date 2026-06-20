from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from notifications.models import Notification

from borrowd_notifications.models import ChannelType, NotificationData, NotificationType


@dataclass
class NotificationPayload:
    notification: Notification
    notification_type: NotificationType
    template_name: str
    data: NotificationData  # context data to fill the template

    @classmethod
    def from_notification(
        cls, notification: Notification, channels: set[ChannelType]
    ) -> "NotificationPayload":
        notification_type = NotificationType(notification.verb)
        context = NotificationType._get_template_context_for(notification)

        return cls(
            notification=notification,
            notification_type=notification_type,
            template_name=str(notification_type),
            data=NotificationData.create(context, channels),
        )


class NotificationStrategy(ABC):
    @abstractmethod
    def send(self, notification_info: NotificationPayload) -> None:
        pass


class EmailNotificationStrategy(NotificationStrategy):
    def send(self, payload: NotificationPayload) -> None:
        """Send an email notification."""

        try:
            text_message = render_to_string(
                f"notifications/messages/{payload.template_name}.txt",
                payload.data.context,
            )
            html_message = render_to_string(
                f"notifications/messages/{payload.template_name}.html",
                payload.data.context,
            )

            self._send_email(
                payload.notification.recipient.email,
                payload.notification.description,
                text=text_message,
                html=html_message,
            )
            payload.notification.emailed = True
            payload.data._success(channel=ChannelType.EMAIL)
        except Exception as e:
            payload.notification.emailed = False
            payload.data._error(channel=ChannelType.EMAIL, error=str(e))
            raise

    def _send_email(self, to_email: str, subject: str, text: str, html: str) -> None:
        if "@" not in to_email:
            raise ValueError("Invalid email address")
        send_mail(
            subject,
            message=text,
            html_message=html,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
        )


class AppNotificationStrategy(NotificationStrategy):
    def send(self, payload: NotificationPayload) -> None:
        try:
            # TODO: Migration to a push-based channel for real-time updates
            # use_sse_channe(notification)

            payload.data._success(channel=ChannelType.APP)
        except Exception as e:
            payload.data._error(channel=ChannelType.APP, error=str(e))
            raise


class PUSHNotificationStrategy(NotificationStrategy):
    def send(self, payload: NotificationPayload) -> None:
        # Push delivery is not yet implemented; intentionally a no-op so the
        # audit trail on the notification row never shows a false SUCCESS.
        # Will be implemented in a different PR
        pass
