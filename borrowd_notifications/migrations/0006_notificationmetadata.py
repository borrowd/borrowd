import django.db.models.deletion
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def backfill_in_app_visibility(
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

    NotificationMetadata.objects.bulk_create(metadata, batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        (
            "borrowd_notifications",
            "0005_seed_item_return_requested_and_disputed_preferences",
        ),
        (
            "notifications",
            "0010_rename_notification_recipient_unread_notificatio_recipie_8bedf2_idx",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationMetadata",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "visible_in_app",
                    models.BooleanField(db_index=True, default=False),
                ),
                (
                    "notification",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="borrowd_metadata",
                        to="notifications.notification",
                    ),
                ),
            ],
        ),
        migrations.RunPython(backfill_in_app_visibility, migrations.RunPython.noop),
    ]
