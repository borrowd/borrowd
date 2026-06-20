import itertools

from django.conf import settings
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

_NEW_TYPES = [
    "Item return requested",
    "Item disputed",
]


def seed_preferences(apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    NotificationPreference = apps.get_model(
        "borrowd_notifications", "NotificationPreference"
    )
    User = apps.get_model(settings.AUTH_USER_MODEL)

    user_ids = list(User.objects.values_list("id", flat=True))
    NotificationPreference.objects.bulk_create(
        [
            NotificationPreference(
                user_id=user_id,
                notification_type=ntype,
                in_app_enabled=True,
                email_enabled=True,
                push_enabled=False,
            )
            for user_id, ntype in itertools.product(user_ids, _NEW_TYPES)
        ],
        batch_size=500,
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        (
            "borrowd_notifications",
            "0004_alter_notificationpreference_notification_type",
        ),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(seed_preferences, migrations.RunPython.noop),
    ]
