from django.conf import settings
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

_NEW_NOTIFICATION_TYPE = "GROUP_CREATED_NEEDS_PHOTO"


def seed_group_created_needs_photo_preferences(
    apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor
) -> None:
    NotificationPreference = apps.get_model(
        "borrowd_notifications", "NotificationPreference"
    )
    User = apps.get_model(settings.AUTH_USER_MODEL)

    user_ids = list(User.objects.values_list("id", flat=True))
    NotificationPreference.objects.bulk_create(
        [
            NotificationPreference(
                user_id=user_id,
                notification_type=_NEW_NOTIFICATION_TYPE,
                in_app_enabled=True,
                email_enabled=True,
                push_enabled=False,
            )
            for user_id in user_ids
        ],
        batch_size=500,
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        (
            "borrowd_notifications",
            "0011_alter_notificationpreference_notification_type",
        ),
    ]

    operations = [
        migrations.RunPython(
            seed_group_created_needs_photo_preferences, migrations.RunPython.noop
        ),
    ]
