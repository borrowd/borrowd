import itertools

from django.conf import settings
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

_ALL_NOTIFICATION_TYPES = [
    "ITEM_REQUESTED",
    "ITEM_REQUEST_ACCEPTED",
    "ITEM_REQUEST_DENIED",
    "COLLECTION_ASSERTED",
    "COLLECTION_CONFIRMED",
    "RETURN_ASSERTED",
    "RETURN_CONFIRMED",
    "ITEM_NOTIFY_WHEN_AVAILABLE",
    "ITEM_SUBSCRIPTION",
    "ITEM_RETURN_REQUESTED",
    "ITEM_DISPUTED",
    "GROUP_MEMBER_JOINED",
    "GROUP_NEEDS_MODERATOR",
    "MEMBERSHIP_PENDING",
    "MEMBERSHIP_APPROVED",
    "COMMUNITY_REQUEST_POSTED",
    "COMMUNITY_REQUEST_FULFILLED",
    "REQUEST_CANCELLED_BORROWER_LEFT",
    "REQUEST_CANCELLED_OWNER_LEFT",
    "LOAN_ENDED_OWNER_LEFT",
]

_LEGACY_NOTIFICATION_TYPE_KEYS = {
    "Item requested": "ITEM_REQUESTED",
    "Item request accepted": "ITEM_REQUEST_ACCEPTED",
    "Item request denied": "ITEM_REQUEST_DENIED",
    "Collection asserted": "COLLECTION_ASSERTED",
    "Collection confirmed": "COLLECTION_CONFIRMED",
    "Return asserted": "RETURN_ASSERTED",
    "Return confirmed": "RETURN_CONFIRMED",
    "Item notify when available": "ITEM_NOTIFY_WHEN_AVAILABLE",
    "Item subscription": "ITEM_SUBSCRIPTION",
    "Item return requested": "ITEM_RETURN_REQUESTED",
    "Item disputed": "ITEM_DISPUTED",
    "A member joined a group you're part of": "GROUP_MEMBER_JOINED",
    "Group needs moderator": "GROUP_NEEDS_MODERATOR",
    "Membership pending": "MEMBERSHIP_PENDING",
    "Membership approved": "MEMBERSHIP_APPROVED",
    "Community request posted": "COMMUNITY_REQUEST_POSTED",
    "Community request fulfilled": "COMMUNITY_REQUEST_FULFILLED",
    "Request cancelled - borrower left": "REQUEST_CANCELLED_BORROWER_LEFT",
    "Request cancelled - owner left": "REQUEST_CANCELLED_OWNER_LEFT",
    "Loan ended - owner left": "LOAN_ENDED_OWNER_LEFT",
}


def normalize_notification_type_keys(
    apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor
) -> None:
    Notification = apps.get_model("notifications", "Notification")
    NotificationPreference = apps.get_model(
        "borrowd_notifications", "NotificationPreference"
    )

    for legacy_key, stable_key in _LEGACY_NOTIFICATION_TYPE_KEYS.items():
        Notification.objects.filter(verb=legacy_key).update(verb=stable_key)
        NotificationPreference.objects.filter(notification_type=legacy_key).update(
            notification_type=stable_key
        )


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
        migrations.RunPython(
            normalize_notification_type_keys, migrations.RunPython.noop
        ),
        migrations.RunPython(seed_notification_preferences, migrations.RunPython.noop),
        migrations.RunPython(backfill_notification_metadata, migrations.RunPython.noop),
    ]
