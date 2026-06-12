import itertools

from django.conf import settings
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

NEW_NOTIFICATION_TYPES = [
    "Collection asserted",
    "Collection confirmed",
    "Return asserted",
    "Return confirmed",
    "Membership pending",
    "Membership approved",
    "Community request posted",
    "Community request fulfilled",
]

ACTIVE_CHANNELS = ["APP", "EMAIL"]


def seed_default_preferences(
    apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor
) -> None:
    NotificationPreference = apps.get_model(
        "borrowd_notifications", "NotificationPreference"
    )
    User = apps.get_model(settings.AUTH_USER_MODEL)

    all_types = [
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

    existing_keys = set(
        NotificationPreference.objects.values_list(
            "user_id", "notification_type", "channel"
        )
    )

    to_create = [
        NotificationPreference(
            user_id=user_id,
            notification_type=notification_type,
            channel=channel,
        )
        for user_id, notification_type, channel in itertools.product(
            User.objects.values_list("id", flat=True),
            all_types,
            ACTIVE_CHANNELS,
        )
        if (user_id, notification_type, channel) not in existing_keys
    ]

    NotificationPreference.objects.bulk_create(to_create, batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        (
            "borrowd_notifications",
            "0002_alter_notificationpreference_notification_type",
        ),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="notificationpreference",
            name="notification_type",
            field=models.CharField(
                choices=[
                    ("Item requested", "Item Requested"),
                    ("Item request accepted", "Item Request Accepted"),
                    ("Item request denied", "Item Request Denied"),
                    ("Collection asserted", "Collection Asserted"),
                    ("Collection confirmed", "Collection Confirmed"),
                    ("Return asserted", "Return Asserted"),
                    ("Return confirmed", "Return Confirmed"),
                    ("Item returned", "Item Returned"),
                    ("Item notify when available", "Item Notify When Available"),
                    ("Item subscription", "Item Subscription"),
                    ("Change to group membership", "Change To Group Membership"),
                    ("Group needs moderator", "Group Needs Moderator"),
                    ("Membership pending", "Membership Pending"),
                    ("Membership approved", "Membership Approved"),
                    ("Community request posted", "Community Request Posted"),
                    (
                        "Community request fulfilled",
                        "Community Request Fulfilled",
                    ),
                ]
            ),
        ),
        migrations.AddConstraint(
            model_name="notificationpreference",
            constraint=models.UniqueConstraint(
                fields=["user", "notification_type", "channel"],
                name="unique_notification_preference",
            ),
        ),
        migrations.RunPython(seed_default_preferences, migrations.RunPython.noop),
    ]
