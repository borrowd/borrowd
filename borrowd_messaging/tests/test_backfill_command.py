from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.utils import timezone

from borrowd_items.models import (
    TERMINAL_TRANSACTION_STATUSES,
    Item,
    Transaction,
    TransactionStatus,
)
from borrowd_messaging.management.commands.backfill_transaction_threads import Command
from borrowd_messaging.models import ChatThread
from borrowd_messaging.services import MessagingService
from borrowd_messaging.tests.base import MessagingTestCase
from borrowd_users.models import BorrowdUser
from borrowd_users.system import SYSTEM_USER_USERNAME, get_system_user


class BackfillTransactionThreadsTests(MessagingTestCase):
    """The one-off command that gives pre-flag Transactions their conversation.

    Transactions created while messaging is off never get a thread from the
    signal, which is the state this command exists to repair.
    """

    def run_command(self, *args: str) -> str:
        out = StringIO()
        call_command(
            "backfill_transaction_threads", *args, stdout=out, stderr=StringIO()
        )
        return out.getvalue()

    def test_links_an_open_transaction_as_the_system_user(self) -> None:
        transaction = self.make_transaction()

        output = self.run_command()

        thread = ChatThread.objects.get(transaction=transaction)
        self.assertEqual(thread.created_by, get_system_user())
        self.assertEqual(thread.updated_by, get_system_user())
        self.assertIn("Linked 1 of 1", output)

    def test_dry_run_reports_the_count_and_creates_nothing(self) -> None:
        self.make_transaction()
        self.make_transaction(item=self.make_item(name="Ladder"))

        output = self.run_command("--dry-run")

        self.assertIn("2 open transaction(s)", output)
        self.assertFalse(ChatThread.objects.exists())

    def test_skips_rows_the_backfill_should_leave_alone(self) -> None:
        for status in TERMINAL_TRANSACTION_STATUSES:
            self.make_transaction(
                item=self.make_item(name=f"Item {status.name}"), status=status
            )
        removed_item = self.make_item(name="Removed")
        self.make_transaction(item=removed_item)
        removed_item.soft_delete(deleted_by=self.lender)
        deleted = self.make_transaction(item=self.make_item(name="Gone"))
        Transaction.objects.filter(pk=deleted.pk).update(deleted_at=timezone.now())

        output = self.run_command()

        self.assertFalse(ChatThread.objects.exists())
        self.assertIn("Linked 0 of 0", output)

    def test_claims_the_borrowers_existing_conversation(self) -> None:
        # The transaction comes first: otherwise its own signal claims the thread.
        transaction = self.make_transaction()
        thread = self.make_thread()

        self.run_command()

        thread.refresh_from_db()
        self.assertEqual(ChatThread.objects.count(), 1)
        self.assertEqual(thread.transaction, transaction)
        self.assertEqual(thread.updated_by, get_system_user())
        self.assertEqual(
            list(thread.messages.values_list("body", flat=True)),
            ["This item has been requested."],
        )

    def test_a_row_changed_after_the_scan_is_skipped(self) -> None:
        cancelled = self.make_transaction()
        deleted = self.make_transaction(item=self.make_item(name="Ladder"))
        Transaction.objects.filter(pk=cancelled.pk).update(
            status=TransactionStatus.CANCELLED
        )
        Transaction.objects.filter(pk=deleted.pk).update(deleted_at=timezone.now())
        command = Command()

        self.assertFalse(command._backfill(cancelled.pk, get_system_user()))
        self.assertFalse(command._backfill(deleted.pk, get_system_user()))
        self.assertFalse(ChatThread.objects.exists())

    def test_a_disputed_transaction_gets_one_notice_across_reruns(self) -> None:
        transaction = self.make_transaction(status=TransactionStatus.DISPUTED)

        self.run_command()
        self.run_command()

        thread = ChatThread.objects.get(transaction=transaction)
        notice = thread.messages.get()
        self.assertTrue(notice.is_system)
        self.assertIn("dispute has been raised", notice.body)

    def test_a_failure_still_links_later_rows_and_exits_non_zero(self) -> None:
        first = self.make_transaction()
        second = self.make_transaction(item=self.make_item(name="Ladder"))
        attach = MessagingService.attach_thread_to

        def flaky(
            transaction: Transaction, actor: BorrowdUser | None = None
        ) -> ChatThread:
            if transaction.pk == first.pk:
                raise RuntimeError("attachment unavailable")
            return attach(transaction, actor=actor)

        errors = StringIO()
        with patch.object(MessagingService, "attach_thread_to", side_effect=flaky):
            with self.assertRaises(CommandError) as raised:
                call_command(
                    "backfill_transaction_threads",
                    stdout=StringIO(),
                    stderr=errors,
                )

        self.assertIn("1 failed", str(raised.exception))
        self.assertIn(f"Failed on transaction {first.pk}", errors.getvalue())
        self.assertFalse(ChatThread.objects.filter(transaction=first).exists())
        self.assertTrue(ChatThread.objects.filter(transaction=second).exists())


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks.")
class BackfillLockingTests(TransactionTestCase):
    """Locking the Item makes a concurrent removal wait for the backfill."""

    def setUp(self) -> None:
        # TransactionTestCase truncates migration data, so make the system user here.
        BorrowdUser.objects.get_or_create(username=SYSTEM_USER_USERNAME)
        self.lender = BorrowdUser.objects.create_user(username="backfill-lender")
        self.borrower = BorrowdUser.objects.create_user(username="backfill-borrower")
        self.item = Item.objects.create(
            name="Drill",
            description="A drill",
            owner=self.lender,
            created_by=self.lender,
            updated_by=self.lender,
        )
        self.transaction = Transaction.objects.create(
            item=self.item,
            party1=self.lender,
            party2=self.borrower,
            created_by=self.borrower,
            updated_by=self.borrower,
        )

    def test_item_removal_waits_for_the_backfill_to_commit(self) -> None:
        lock_held = Event()
        allow_commit = Event()
        removal_started = Event()
        removal_finished = Event()
        attach = MessagingService.attach_thread_to

        def pause_inside_the_lock(
            transaction: Transaction, actor: BorrowdUser | None = None
        ) -> ChatThread:
            lock_held.set()
            if not allow_commit.wait(timeout=10):
                raise TimeoutError("Timed out holding the backfill transaction.")
            return attach(transaction, actor=actor)

        def backfill() -> bool:
            close_old_connections()
            try:
                return Command()._backfill(self.transaction.pk, get_system_user())
            finally:
                connections.close_all()

        def remove_the_item() -> None:
            close_old_connections()
            try:
                removal_started.set()
                Item.objects.get(pk=self.item.pk).soft_delete(deleted_by=self.lender)
                removal_finished.set()
            finally:
                connections.close_all()

        with patch.object(
            MessagingService, "attach_thread_to", side_effect=pause_inside_the_lock
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                try:
                    linked = executor.submit(backfill)
                    self.assertTrue(lock_held.wait(timeout=10))
                    removal = executor.submit(remove_the_item)
                    self.assertTrue(removal_started.wait(timeout=10))
                    # The removal's UPDATE waits on the Item row this backfill holds.
                    self.assertFalse(removal_finished.wait(timeout=0.5))
                finally:
                    allow_commit.set()

                self.assertTrue(linked.result(timeout=10))
                removal.result(timeout=10)

        # The removal ran second, so its archive pass covered the new conversation.
        thread = ChatThread.objects.get(transaction=self.transaction)
        self.assertIsNotNone(thread.archived_at)
