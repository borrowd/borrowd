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
                            ("ITEM_REQUESTED", "Item Requested"),
                            ("ITEM_REQUEST_ACCEPTED", "Item Request Accepted"),
                            ("ITEM_REQUEST_DENIED", "Item Request Denied"),
                            ("COLLECTION_ASSERTED", "Collection Asserted"),
                            ("COLLECTION_CONFIRMED", "Collection Confirmed"),
                            ("RETURN_ASSERTED", "Return Asserted"),
                            ("RETURN_CONFIRMED", "Return Confirmed"),
                            (
                                "ITEM_NOTIFY_WHEN_AVAILABLE",
                                "Item Notify When Available",
                            ),
                            ("ITEM_SUBSCRIPTION", "Item Subscription"),
                            ("ITEM_RETURN_REQUESTED", "Item Return Requested"),
                            ("ITEM_DISPUTED", "Item Disputed"),
                            ("GROUP_MEMBER_JOINED", "Group Member Joined"),
                            ("GROUP_NEEDS_MODERATOR", "Group Needs Moderator"),
                            ("MEMBERSHIP_PENDING", "Membership Pending"),
                            ("MEMBERSHIP_APPROVED", "Membership Approved"),
                            (
                                "COMMUNITY_REQUEST_POSTED",
                                "Community Request Posted",
                            ),
                            (
                                "COMMUNITY_REQUEST_FULFILLED",
                                "Community Request Fulfilled",
                            ),
                            (
                                "REQUEST_CANCELLED_BORROWER_LEFT",
                                "Request Cancelled Borrower Left",
                            ),
                            (
                                "REQUEST_CANCELLED_OWNER_LEFT",
                                "Request Cancelled Owner Left",
                            ),
                            ("LOAN_ENDED_OWNER_LEFT", "Loan Ended Owner Left"),
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
