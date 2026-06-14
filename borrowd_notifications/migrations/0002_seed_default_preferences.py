import itertools

from django.conf import settings
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

ALL_NOTIFICATION_TYPES = [
    "Item requested",
    "Item request accepted",
    "Item request denied",
    "Collection asserted",
    "Collection confirmed",
    "Return asserted",
    "Return confirmed",
    "Item returned",
    "Item notify when available",
    "Item subscription",
    "Change to group membership",
    "Group needs moderator",
    "Membership pending",
    "Membership approved",
    "Community request posted",
    "Community request fulfilled",
]


def seed_default_preferences(
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
                notification_type=ntype,
                in_app_enabled=True,
                email_enabled=True,
                push_enabled=False,
            )
            for user_id, ntype in itertools.product(user_ids, ALL_NOTIFICATION_TYPES)
        ],
        batch_size=500,
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("borrowd_notifications", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(seed_default_preferences, migrations.RunPython.noop),
    ]
