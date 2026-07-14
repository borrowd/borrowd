from typing import Any

from django.core.management.base import BaseCommand

from borrowd_notifications.services import NotificationService


class Command(BaseCommand):
    help = "Send pending summary digest emails to throttled users"

    def handle(self, *args: Any, **options: Any) -> None:
        sent = NotificationService.send_pending_digests()
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} summary digest emails"))
