from datetime import timedelta
from io import StringIO
from uuid import uuid4

from django.core.management import call_command
from django.utils import timezone

from borrowd_items.commands import run_item_command
from borrowd_items.exceptions import StaleItemCommand
from borrowd_items.models import ItemAction, ItemCommandRecord
from borrowd_items.tests.test_item_commands import CommandTestCase


class PruneCommandRecordsTests(CommandTestCase):
    def test_drops_records_past_the_retention_window(self) -> None:
        kept = self.run_as(
            self.alice, ItemAction.REQUEST_ITEM, key=uuid4(), revision=self.revision()
        )
        self.run_as(
            self.alice, ItemAction.CANCEL_REQUEST, key=uuid4(), revision=self.revision()
        )
        ItemCommandRecord.objects.filter(action=ItemAction.CANCEL_REQUEST).update(
            created_at=timezone.now() - timedelta(days=31)
        )
        out = StringIO()

        call_command("prune_item_command_records", stdout=out)

        self.assertEqual(
            list(ItemCommandRecord.objects.values_list("transaction_id", flat=True)),
            [kept.transaction_id],
        )
        self.assertIn("Pruned 1 command record(s)", out.getvalue())

    def test_a_pruned_key_cannot_repeat_a_completed_request(self) -> None:
        command = self.command(
            self.alice, ItemAction.REQUEST_ITEM, key=uuid4(), revision=0
        )
        run_item_command(command)
        self.item.process_action(self.alice, ItemAction.CANCEL_REQUEST)
        ItemCommandRecord.objects.update(created_at=timezone.now() - timedelta(days=31))
        call_command("prune_item_command_records", stdout=StringIO())
        with self.assertRaises(StaleItemCommand):
            run_item_command(command)
