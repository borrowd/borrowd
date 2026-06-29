import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from notifications.models import Notification
from pywebpush import (
    WebPushException,
    webpush,
)

from borrowd_notifications.models import (
    ChannelType,
    NotificationData,
    NotificationType,
    PushSubscription,
)


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
            # use sse/websocket channel

            payload.data._success(channel=ChannelType.APP)
        except Exception as e:
            payload.data._error(channel=ChannelType.APP, error=str(e))
            raise


class PUSHNotificationStrategy(NotificationStrategy):
    def send(self, payload: NotificationPayload) -> None:
        """
        Sends web-push notifications to all of the user subscribed browser.
        This would work for open browsers tabs and open/closed pwa.
        No native push framework required.
        """
        subscriptions = list(
            PushSubscription.objects.filter(user=payload.notification.recipient)
        )
        if not subscriptions:
            payload.data._error(
                channel=ChannelType.PUSH, error="No subscription for this device."
            )
            return

        context = payload.data.context
        try:
            body = payload.notification_type.message_template.format(**context)
        except KeyError:
            body = payload.notification_type

        base_url = settings.BASE_URL.rstrip("/")
        push_data = json.dumps(
            {
                "title": "Borrow'd",
                "body": body,
                "icon": f"{base_url}/static/icon.svg",  # safari doesnt support this.
                "url": (
                    context.get("respond_url")
                    or context.get("item_url")
                    or context.get("group_url")
                    or f"{base_url}/notifications/"
                ),
            }
        )

        errors: list[str] = []
        for sub in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    data=push_data,
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": f"mailto:{settings.VAPID_ADMIN_EMAIL}"},
                )
            except WebPushException as exc:
                errors.append(str(exc))
                if exc.response is not None and exc.response.status_code in (404, 410):
                    sub.delete()
            except Exception as exc:
                errors.append(str(exc))

        if errors:
            payload.data._error(channel=ChannelType.PUSH, error="; ".join(errors))
        else:
            payload.data._success(channel=ChannelType.PUSH)
