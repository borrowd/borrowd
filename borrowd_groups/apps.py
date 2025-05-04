from django.apps import AppConfig


class BorrowdGroupsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "borrowd_groups"

    def ready(self) -> None:
        # Unfortunately this unusued import is the recommended
        # approach when using the `@receiver` decorator; see
        # section "Where should this code live?" in the docs:
        # https://docs.djangoproject.com/en/5.1/topics/signals/
        import borrowd_groups.signals  # noqa
