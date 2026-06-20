import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        (
            "notifications",
            "0010_rename_notification_recipient_unread_notificatio_recipie_8bedf2_idx",
        ),
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
                        choices=[
                            (
                                "Item requested",
                                "{requester_name} wants to borrow your {item_name}",
                            ),
                            (
                                "Item request accepted",
                                "{item_owner_name} accepted your request for {item_name}",
                            ),
                            (
                                "Item request denied",
                                "{item_owner_name} declined your request for {item_name}",
                            ),
                            (
                                "Collection asserted",
                                "{requester_name} says they have collected {item_name}",
                            ),
                            (
                                "Collection confirmed",
                                "{item_owner_name} confirmed collection of {item_name}",
                            ),
                            (
                                "Return asserted",
                                "{requester_name} says they have returned {item_name}",
                            ),
                            (
                                "Return confirmed",
                                "{item_owner_name} confirmed the return of {item_name}",
                            ),
                            (
                                "Item notify when available",
                                "{owner_name} has {item_name} available to borrow",
                            ),
                            (
                                "Item subscription",
                                "{subscriber_name} subscribed to be notified when {item_name} becomes available",
                            ),
                            (
                                "Item return requested",
                                "{owner_name} requested the return of {item_name}",
                            ),
                            (
                                "Item disputed",
                                "{dispute_raiser_name} raised a dispute over {item_name}",
                            ),
                            (
                                "A member joined a group you're part of",
                                "{new_member_name} joined {group_name}",
                            ),
                            (
                                "Group needs moderator",
                                "{actor_name} left {group_name} — the group needs a moderator",
                            ),
                            (
                                "Membership pending",
                                "{new_member_name} has requested to join {group_name}",
                            ),
                            (
                                "Membership approved",
                                "{group_name} approved your membership",
                            ),
                            (
                                "Community request posted",
                                "A new community request was posted in {group_name}",
                            ),
                            (
                                "Community request fulfilled",
                                "A community request in {group_name} was fulfilled",
                            ),
                            (
                                "Request cancelled - borrower left",
                                "{actor_name}'s borrow request for {item_name} was cancelled",
                            ),
                            (
                                "Request cancelled - owner left",
                                "{actor_name} left — your request for {item_name} was cancelled",
                            ),
                            (
                                "Loan ended - owner left",
                                "{actor_name} left — your loan of {item_name} has ended",
                            ),
                        ],
                        max_length=100,
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
                ("visible_in_app", models.BooleanField(db_index=True, default=False)),
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
    ]
