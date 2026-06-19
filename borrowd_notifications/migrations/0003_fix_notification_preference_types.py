import itertools

from django.conf import settings
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

_RENAMES = {
    "Change to group membership": "A member joined a group you're part of",
}

_STALE_TYPES = [
    "Item returned",
]

_NEW_TYPES = [
    "A member joined a group you're part of",
    "Request cancelled - borrower left",
    "Request cancelled - owner left",
    "Loan ended - owner left",
]


def fix_preference_types(
    apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor
) -> None:
    NotificationPreference = apps.get_model(
        "borrowd_notifications", "NotificationPreference"
    )
    User = apps.get_model(settings.AUTH_USER_MODEL)

    for old, new in _RENAMES.items():
        NotificationPreference.objects.filter(notification_type=old).update(
            notification_type=new
        )

    NotificationPreference.objects.filter(notification_type__in=_STALE_TYPES).delete()

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
        ("borrowd_notifications", "0002_seed_default_preferences"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(fix_preference_types, migrations.RunPython.noop),
    ]
