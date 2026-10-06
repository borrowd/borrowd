"""Transaction notifications go out from lifecycle events, after the change commits."""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.utils import timezone
from notifications.models import Notification
from notifications.signals import notify

from borrowd_items import events
from borrowd_items.models import (
    AvailabilitySubscription,
    AvailabilitySubscriptionStatus,
    Item,
    ItemAction,
    LifecycleEvent,
    LifecycleEventConsumption,
    Transaction,
    TransactionStatus,
)
from borrowd_users.models import BorrowdUser
from borrowd_users.services import soft_delete_account

from .models import NotificationType


class LifecycleNotificationTests(TestCase):
    owner: BorrowdUser
    borrower: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.owner, cls.borrower = (
            BorrowdUser.objects.create_user(
                username=name, email=f"{name}@example.com", password="password"
            )
            for name in ("ln_owner", "ln_borrower")
        )

    def setUp(self) -> None:
        self.item = Item.objects.create(
            name="Drill",
            description="A drill",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
        )

    def requested(self) -> int:
        # django-notifications is untyped, so pin the count's type here.
        count: int = Notification.objects.filter(
            recipient=self.owner, verb=NotificationType.ITEM_REQUESTED.value
        ).count()
        return count

    def test_an_action_notifies_once_its_change_commits(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.item.process_action(self.borrower, ItemAction.REQUEST_ITEM)
            self.assertEqual(self.requested(), 0)

        self.assertEqual(self.requested(), 1)

    def test_a_notification_a_crash_held_up_goes_out_with_the_sweeper(self) -> None:
        # Nothing runs after commit here, as if the process died right then.
        self.item.process_action(self.borrower, ItemAction.REQUEST_ITEM)
        self.assertEqual(self.requested(), 0)

        call_command("deliver_lifecycle_events", stdout=StringIO())

        self.assertEqual(self.requested(), 1)

    def test_a_redelivered_event_notifies_once(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.item.process_action(self.borrower, ItemAction.REQUEST_ITEM)
        LifecycleEvent.objects.update(processed_at=None)

        events.deliver_due()

        self.assertEqual(self.requested(), 1)

    def test_a_failed_notification_leaves_the_action_done_and_retries(self) -> None:
        with (
            mock.patch(
                "borrowd_notifications.lifecycle.notify.send",
                side_effect=RuntimeError("smtp down"),
            ),
            self.assertLogs("borrowd.items.events", level="WARNING"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.item.process_action(self.borrower, ItemAction.REQUEST_ITEM)

        self.assertTrue(Transaction.objects.filter(item=self.item).exists())
        event = LifecycleEvent.objects.get()
        self.assertEqual(event.attempts, 1)
        self.assertIn("smtp down", event.last_error)
        self.assertEqual(self.requested(), 0)

        events.deliver_due(now=timezone.now() + timedelta(hours=1))

        self.assertEqual(self.requested(), 1)

    def test_a_request_cancelled_by_account_closure_frees_the_item(self) -> None:
        watcher = BorrowdUser.objects.create_user(
            username="ln_watcher", email="ln_watcher@example.com"
        )
        self.item.process_action(self.borrower, ItemAction.REQUEST_ITEM)
        AvailabilitySubscription.objects.create(
            user=watcher, item=self.item, status=AvailabilitySubscriptionStatus.ACTIVE
        )

        with self.captureOnCommitCallbacks(execute=True):
            soft_delete_account(self.borrower, deleted_by=self.borrower)

        self.assertTrue(
            Notification.objects.filter(
                recipient=watcher,
                verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
            ).exists()
        )

    def test_pending_events_from_synchronous_writers_do_not_notify_again(self) -> None:
        tx = Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            created_by=self.borrower,
            updated_by=self.borrower,
        )
        notify.send(
            self.borrower,
            recipient=[self.owner],
            verb=NotificationType.ITEM_REQUESTED.value,
            action_object=self.item,
            target=tx,
        )
        Notification.objects.update(timestamp=timezone.now() - timedelta(hours=1))
        old_apps = (
            MigrationExecutor(connection)
            .loader.project_state([("borrowd_items", "0029_lifecycle_events")])
            .apps
        )
        old_event = old_apps.get_model(
            "borrowd_items", "LifecycleEvent"
        ).objects.create(
            item_id=self.item.pk,
            transaction_id=tx.pk,
            revision=1,
            target_status=TransactionStatus.REQUESTED,
            actor_id=self.borrower.pk,
        )
        self.assertEqual(old_event.schema_version, 1)
        with mock.patch("borrowd_notifications.lifecycle.notify.send") as send:
            events.deliver_due()
        send.assert_not_called()
        self.assertEqual(self.requested(), 1)
        self.assertTrue(
            LifecycleEventConsumption.objects.filter(
                event_id=old_event.pk, consumer="notifications"
            ).exists()
        )

    def test_new_events_use_the_notification_consumer_version(self) -> None:
        self.item.process_action(self.borrower, ItemAction.REQUEST_ITEM)
        self.assertEqual(LifecycleEvent.objects.get().schema_version, 2)
        events.deliver_due()
        self.assertEqual(self.requested(), 1)
