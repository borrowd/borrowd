import itertools

from django.conf import settings
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

_ALL_NOTIFICATION_TYPES = [
    "Item requested",
    "Item request accepted",
    "Item request denied",
    "Collection asserted",
    "Collection confirmed",
    "Return asserted",
    "Return confirmed",
    "Item notify when available",
    "Item subscription",
    "Item return requested",
    "Item disputed",
    "A member joined a group you're part of",
    "Group needs moderator",
    "Membership pending",
    "Membership approved",
    "Community request posted",
    "Community request fulfilled",
    "Request cancelled - borrower left",
    "Request cancelled - owner left",
    "Loan ended - owner left",
]


def seed_notification_preferences(
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
                notification_type=notification_type,
                in_app_enabled=True,
                email_enabled=True,
                push_enabled=False,
            )
            for user_id, notification_type in itertools.product(
                user_ids, _ALL_NOTIFICATION_TYPES
            )
        ],
        batch_size=500,
        ignore_conflicts=True,
    )


def backfill_notification_metadata(
    apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor
) -> None:
    Notification = apps.get_model("notifications", "Notification")
    NotificationMetadata = apps.get_model(
        "borrowd_notifications", "NotificationMetadata"
    )

    metadata = []
    for notification in Notification.objects.only("pk", "data").iterator():
        data = notification.data
        channels = data.get("channels") if isinstance(data, dict) else None
        metadata.append(
            NotificationMetadata(
                notification_id=notification.pk,
                visible_in_app=isinstance(channels, dict) and "APP" in channels,
            )
        )

    NotificationMetadata.objects.bulk_create(
        metadata, batch_size=500, ignore_conflicts=True
    )


class Migration(migrations.Migration):
    dependencies = [
        ("borrowd_notifications", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_notification_preferences, migrations.RunPython.noop),
        migrations.RunPython(backfill_notification_metadata, migrations.RunPython.noop),
    ]
