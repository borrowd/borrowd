import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationPreference",
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
                    "notification_type",
                    models.CharField(
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
                            (
                                "Item notify when available",
                                "Item Notify When Available",
                            ),
                            ("Item subscription", "Item Subscription"),
                            (
                                "Change to group membership",
                                "Change To Group Membership",
                            ),
                            ("Group needs moderator", "Group Needs Moderator"),
                            ("Membership pending", "Membership Pending"),
                            ("Membership approved", "Membership Approved"),
                            ("Community request posted", "Community Request Posted"),
                            (
                                "Community request fulfilled",
                                "Community Request Fulfilled",
                            ),
                        ],
                    ),
                ),
                ("in_app_enabled", models.BooleanField(default=True)),
                ("email_enabled", models.BooleanField(default=True)),
                ("push_enabled", models.BooleanField(default=False)),
                (
                    "user",
                    models.ForeignKey(
                        help_text="The user who owns these preferences",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications_preferences",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="notificationpreference",
            constraint=models.UniqueConstraint(
                fields=["user", "notification_type"],
                name="unique_notification_preference",
            ),
        ),
    ]
