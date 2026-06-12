import itertools

from django.conf import settings
from django.db import migrations, models
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


def consolidate_to_column_preferences(
    apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor
) -> None:
    NotificationPreference = apps.get_model(
        "borrowd_notifications", "NotificationPreference"
    )
    User = apps.get_model(settings.AUTH_USER_MODEL)

    # Record which channels each (user, type) pair had enabled in the old schema.
    channel_map: dict[tuple[int, str], set[str]] = {}
    for row in NotificationPreference.objects.values(
        "user_id", "notification_type", "channel"
    ):
        key = (row["user_id"], row["notification_type"])
        channel_map.setdefault(key, set()).add(row["channel"])

    NotificationPreference.objects.all().delete()

    user_ids = list(User.objects.values_list("id", flat=True))
    NotificationPreference.objects.bulk_create(
        [
            NotificationPreference(
                user_id=user_id,
                notification_type=ntype,
                in_app_enabled="APP" in channel_map.get((user_id, ntype), {"APP"}),
                email_enabled="EMAIL" in channel_map.get((user_id, ntype), {"EMAIL"}),
                push_enabled=False,
            )
            for user_id, ntype in itertools.product(user_ids, ALL_NOTIFICATION_TYPES)
        ],
        batch_size=500,
    )


class Migration(migrations.Migration):
    dependencies = [
        (
            "borrowd_notifications",
            "0003_notificationpreference_unique_constraint_and_new_types",
        ),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="notificationpreference",
            name="unique_notification_preference",
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="in_app_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="email_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="push_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            consolidate_to_column_preferences, migrations.RunPython.noop
        ),
        migrations.RemoveField(
            model_name="notificationpreference",
            name="channel",
        ),
        migrations.AlterField(
            model_name="notificationpreference",
            name="notification_type",
            field=models.CharField(
                max_length=100,
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
                    ("Community request fulfilled", "Community Request Fulfilled"),
                ],
            ),
        ),
        migrations.AddConstraint(
            model_name="notificationpreference",
            constraint=models.UniqueConstraint(
                fields=["user", "notification_type"],
                name="unique_notification_preference",
            ),
        ),
    ]
