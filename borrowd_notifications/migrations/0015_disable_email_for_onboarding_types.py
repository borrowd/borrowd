from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

_EMAIL_EXCLUDED_TYPES = [
    "ITEM_ADDED_NEEDS_GROUP",
    "GROUP_CREATED_NEEDS_PHOTO",
    "PHOTO_ADDED_NEEDS_INVITES",
]


def disable_email_for_onboarding_types(
    apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor
) -> None:
    NotificationPreference = apps.get_model(
        "borrowd_notifications", "NotificationPreference"
    )
    NotificationPreference.objects.filter(
        notification_type__in=_EMAIL_EXCLUDED_TYPES,
        email_enabled=True,
    ).update(email_enabled=False)


class Migration(migrations.Migration):
    dependencies = [
        (
            "borrowd_notifications",
            "0014_seed_photo_added_needs_invites_preferences",
        ),
    ]

    operations = [
        migrations.RunPython(
            disable_email_for_onboarding_types, migrations.RunPython.noop
        ),
    ]
