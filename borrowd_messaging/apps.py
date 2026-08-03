from django.apps import AppConfig


class MessagingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "borrowd_messaging"

    def ready(self) -> None:
        # Unfortunately this unusued import is the recommended
        # approach when using the `@receiver` decorator; see
        # section "Where should this code live?" in the docs:
        # https://docs.djangoproject.com/en/5.2/topics/signals/
        import borrowd_messaging.signals  # noqa
