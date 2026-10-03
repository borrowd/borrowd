"""Checking on and unsticking event delivery, from cron, the shell and the admin."""

from io import StringIO
from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.test import RequestFactory
from django.utils import timezone

from borrowd_items.admin import LifecycleEventAdmin
from borrowd_items.models import ItemAction, LifecycleEvent
from borrowd_items.tests.test_lifecycle_events import EventTestCase, consumers


class EventOperationsTests(EventTestCase):
    def test_the_sweeper_command_delivers_and_counts(self) -> None:
        self.requested_item()
        out = StringIO()
        with consumers():
            call_command("deliver_lifecycle_events", stdout=out)
        self.assertIn("Delivered 1 event(s). 0 waiting, 0 parked.", out.getvalue())

    def test_status_lists_parked_events(self) -> None:
        self.requested_item()
        LifecycleEvent.objects.update(failed_at=timezone.now(), last_error="x: boom")
        out = StringIO()
        call_command("lifecycle_events", "status", stdout=out)
        self.assertIn("0 waiting (oldest -), 1 parked.", out.getvalue())
        self.assertIn("x: boom", out.getvalue())

    def test_replay_and_skip_from_the_command_line(self) -> None:
        item, tx = self.requested_item()
        item.process_action(self.lender, ItemAction.ACCEPT_REQUEST)
        first, second = self.events_for(tx)
        LifecycleEvent.objects.update(failed_at=timezone.now())

        with consumers():
            call_command(
                "lifecycle_events",
                "skip",
                str(first.pk),
                "--reason",
                "Sorted out by hand",
                "--by",
                self.lender.username,
                stdout=StringIO(),
            )
            call_command(
                "lifecycle_events", "replay", str(second.pk), stdout=StringIO()
            )

        self.assertTrue(
            all(event.processed_at is not None for event in self.events_for(tx))
        )

    def test_the_admin_replays_and_skips(self) -> None:
        item, tx = self.requested_item()
        item.process_action(self.lender, ItemAction.ACCEPT_REQUEST)
        first, second = self.events_for(tx)
        LifecycleEvent.objects.update(failed_at=timezone.now())
        model_admin = LifecycleEventAdmin(LifecycleEvent, AdminSite())
        request = RequestFactory().post("/")
        request.user = self.lender

        with consumers():
            first.skip_reason = "Handled elsewhere"
            model_admin.save_model(
                request, first, mock.Mock(changed_data=["skip_reason"]), change=True
            )
            model_admin.replay_events(
                request, LifecycleEvent.objects.filter(pk=second.pk)
            )

        first.refresh_from_db()
        self.assertEqual(first.skipped_by_id, self.lender.pk)
        self.assertTrue(
            all(event.processed_at is not None for event in self.events_for(tx))
        )
