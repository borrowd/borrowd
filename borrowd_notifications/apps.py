from django.apps import AppConfig


class BorrowdNotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "borrowd_notifications"
    verbose_name = "Borrow'd Notifications"

    def ready(self) -> None:
        """Import signals when the app is ready."""
        import borrowd_notifications.signals  # noqa
