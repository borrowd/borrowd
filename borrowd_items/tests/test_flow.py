"""Verify transition eligibility."""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from borrowd_items.flow import (
    TRANSITIONS,
    Transition,
    available_actions,
    eligible_transitions,
)
from borrowd_items.models import (
    OPEN_TRANSACTION_STATUSES,
    TERMINAL_TRANSACTION_STATUSES,
    Item,
    ItemAction,
    Transaction,
    TransactionStatus,
)
from borrowd_items.tests.test_item_lifecycle_writes import EXPECTED_WRITES
from borrowd_users.models import BorrowdUser

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=dt_timezone.utc)
WAIT = timedelta(days=settings.RETURN_DISPUTE_WAIT_DAYS)

LENDER = "lender"
BORROWER = "borrower"

# Independent check on the derived set.
IN_HAND_STATUSES = (
    TransactionStatus.COLLECTION_ASSERTED,
    TransactionStatus.COLLECTED,
    TransactionStatus.GIVEAWAY_OFFERED,
    TransactionStatus.RETURN_REQUESTED,
    TransactionStatus.RETURN_ASSERTED,
    TransactionStatus.DISPUTED,
)

# What each party is offered when:
# - the other party acted last,
# - the dispute wait has elapsed,
# - and both accounts are active.
EXPECTED_ACTIONS: dict[tuple[TransactionStatus, str], tuple[ItemAction, ...]] = {
    (TransactionStatus.REQUESTED, LENDER): (
        ItemAction.REJECT_REQUEST,
        ItemAction.ACCEPT_REQUEST,
    ),
    (TransactionStatus.REQUESTED, BORROWER): (ItemAction.CANCEL_REQUEST,),
    (TransactionStatus.GIVEAWAY_REQUESTED, LENDER): (
        ItemAction.DECLINE_GIVEAWAY_REQUEST,
        ItemAction.APPROVE_GIVEAWAY_REQUEST,
    ),
    (TransactionStatus.GIVEAWAY_REQUESTED, BORROWER): (ItemAction.CANCEL_REQUEST,),
    (TransactionStatus.ACCEPTED, LENDER): (
        ItemAction.CANCEL_REQUEST,
        ItemAction.MARK_COLLECTED,
    ),
    (TransactionStatus.ACCEPTED, BORROWER): (
        ItemAction.CANCEL_REQUEST,
        ItemAction.MARK_COLLECTED,
    ),
    (TransactionStatus.COLLECTION_ASSERTED, LENDER): (ItemAction.CONFIRM_COLLECTED,),
    (TransactionStatus.COLLECTION_ASSERTED, BORROWER): (ItemAction.CONFIRM_COLLECTED,),
    (TransactionStatus.COLLECTED, LENDER): (
        ItemAction.CONFIRM_RETURNED,
        ItemAction.REQUEST_RETURN,
        ItemAction.OFFER_GIVEAWAY,
    ),
    (TransactionStatus.COLLECTED, BORROWER): (ItemAction.MARK_RETURNED,),
    (TransactionStatus.GIVEAWAY_OFFERED, LENDER): (),
    (TransactionStatus.GIVEAWAY_OFFERED, BORROWER): (
        ItemAction.ACCEPT_GIVEAWAY,
        ItemAction.DECLINE_GIVEAWAY,
    ),
    (TransactionStatus.RETURN_REQUESTED, LENDER): (
        ItemAction.RAISE_DISPUTE,
        ItemAction.CONFIRM_RETURNED,
    ),
    (TransactionStatus.RETURN_REQUESTED, BORROWER): (
        ItemAction.MARK_RETURNED,
        ItemAction.FLAG_CANNOT_RETURN,
    ),
    (TransactionStatus.RETURN_ASSERTED, LENDER): (
        ItemAction.RAISE_DISPUTE,
        ItemAction.CONFIRM_RETURNED,
    ),
    (TransactionStatus.RETURN_ASSERTED, BORROWER): (ItemAction.CONFIRM_RETURNED,),
    (TransactionStatus.DISPUTED, LENDER): (
        ItemAction.RESOLVE_DISPUTE_NOT_RETURNED,
        ItemAction.RESOLVE_DISPUTE_RETURNED,
    ),
    (TransactionStatus.DISPUTED, BORROWER): (),
}


class FlowTestCase(SimpleTestCase):
    def setUp(self) -> None:
        self.lender = BorrowdUser(pk=1, username="lender", is_active=True)
        self.borrower = BorrowdUser(pk=2, username="borrower", is_active=True)
        self.bystander = BorrowdUser(pk=3, username="bystander", is_active=True)
        self.item = Item(pk=1, owner=self.lender)

    def party(self, role: str) -> BorrowdUser:
        return self.lender if role == LENDER else self.borrower

    def other(self, role: str) -> BorrowdUser:
        return self.borrower if role == LENDER else self.lender

    def transaction(
        self,
        status: TransactionStatus,
        *,
        updated_by: BorrowdUser,
        return_requested_at: datetime | None = NOW - WAIT,
    ) -> Transaction:
        return Transaction(
            item=self.item,
            party1=self.lender,
            party2=self.borrower,
            status=status,
            updated_by=updated_by,
            return_requested_at=return_requested_at,
        )


class EligibilityTests(FlowTestCase):
    def test_each_party_is_offered_the_expected_actions(self) -> None:
        self.assertEqual(
            {status for status, _ in EXPECTED_ACTIONS}, set(OPEN_TRANSACTION_STATUSES)
        )
        for (status, role), expected in EXPECTED_ACTIONS.items():
            with self.subTest(status=status.name, role=role):
                tx = self.transaction(status, updated_by=self.other(role))
                self.assertEqual(
                    available_actions(tx, self.party(role), now=NOW), expected
                )

    def test_whoever_asserted_a_step_cannot_confirm_it(self) -> None:
        for status in (
            TransactionStatus.COLLECTION_ASSERTED,
            TransactionStatus.RETURN_ASSERTED,
        ):
            for role in (LENDER, BORROWER):
                with self.subTest(status=status.name, role=role):
                    tx = self.transaction(status, updated_by=self.party(role))
                    self.assertEqual(
                        available_actions(tx, self.party(role), now=NOW), ()
                    )

    def test_lender_can_dispute_a_return_request_only_after_the_wait(self) -> None:
        status = TransactionStatus.RETURN_REQUESTED
        cases = (
            ("no return requested", None, False),
            ("one second short", NOW - WAIT + timedelta(seconds=1), False),
            ("exactly the wait", NOW - WAIT, True),
            ("well past the wait", NOW - WAIT - timedelta(days=30), True),
        )
        for label, requested_at, may_dispute in cases:
            with self.subTest(label):
                tx = self.transaction(
                    status, updated_by=self.lender, return_requested_at=requested_at
                )
                actions = available_actions(tx, self.lender, now=NOW)
                self.assertEqual(ItemAction.RAISE_DISPUTE in actions, may_dispute)
                self.assertIn(ItemAction.CONFIRM_RETURNED, actions)

    def test_the_time_comes_from_the_caller_not_the_clock(self) -> None:
        tx = self.transaction(
            TransactionStatus.RETURN_REQUESTED,
            updated_by=self.lender,
            return_requested_at=NOW,
        )
        with mock.patch("django.utils.timezone.now", side_effect=AssertionError):
            before = available_actions(tx, self.lender, now=NOW)
            after = available_actions(tx, self.lender, now=NOW + WAIT)
        self.assertNotIn(ItemAction.RAISE_DISPUTE, before)
        self.assertIn(ItemAction.RAISE_DISPUTE, after)

    def test_someone_who_is_not_a_party_is_offered_nothing(self) -> None:
        for status in TransactionStatus:
            with self.subTest(status=status.name):
                tx = self.transaction(status, updated_by=self.lender)
                self.assertEqual(eligible_transitions(tx, self.bystander, now=NOW), ())

    def test_a_finished_transaction_offers_nothing(self) -> None:
        for status in TERMINAL_TRANSACTION_STATUSES:
            for role in (LENDER, BORROWER):
                with self.subTest(status=status.name, role=role):
                    tx = self.transaction(status, updated_by=self.other(role))
                    self.assertEqual(
                        eligible_transitions(tx, self.party(role), now=NOW), ()
                    )

    def test_an_inactive_counterparty_leaves_only_resolution_once_in_hand(
        self,
    ) -> None:
        for status in IN_HAND_STATUSES:
            for role in (LENDER, BORROWER):
                with self.subTest(status=status.name, role=role):
                    self.other(role).is_active = False
                    tx = self.transaction(status, updated_by=self.other(role))
                    (spec,) = eligible_transitions(tx, self.party(role), now=NOW)
                    self.assertEqual(spec.action, ItemAction.RESOLVE_TRANSACTION)
                    self.assertEqual(spec.target, TransactionStatus.RESOLVED)
                    self.other(role).is_active = True

    def test_an_inactive_counterparty_changes_nothing_before_collection(self) -> None:
        for status in (
            TransactionStatus.REQUESTED,
            TransactionStatus.GIVEAWAY_REQUESTED,
            TransactionStatus.ACCEPTED,
        ):
            for role in (LENDER, BORROWER):
                with self.subTest(status=status.name, role=role):
                    self.other(role).is_active = False
                    tx = self.transaction(status, updated_by=self.other(role))
                    self.assertEqual(
                        available_actions(tx, self.party(role), now=NOW),
                        EXPECTED_ACTIONS[(status, role)],
                    )
                    self.other(role).is_active = True

    def test_an_active_counterparty_is_never_resolved_around(self) -> None:
        for status in IN_HAND_STATUSES:
            for role in (LENDER, BORROWER):
                with self.subTest(status=status.name, role=role):
                    tx = self.transaction(status, updated_by=self.other(role))
                    self.assertNotIn(
                        ItemAction.RESOLVE_TRANSACTION,
                        available_actions(tx, self.party(role), now=NOW),
                    )

    def test_action_names_mirror_the_eligible_transitions(self) -> None:
        tx = self.transaction(TransactionStatus.COLLECTED, updated_by=self.borrower)
        specs = eligible_transitions(tx, self.lender, now=NOW)
        self.assertTrue(all(isinstance(spec, Transition) for spec in specs))
        self.assertEqual(
            tuple(spec.action for spec in specs),
            available_actions(tx, self.lender, now=NOW),
        )


class TransitionTableTests(SimpleTestCase):
    def test_every_open_status_has_a_way_out_and_no_finished_one_does(self) -> None:
        self.assertEqual(
            {spec.source for spec in TRANSITIONS}, set(OPEN_TRANSACTION_STATUSES)
        )

    def test_no_action_is_listed_twice_for_one_source(self) -> None:
        pairs = [(spec.source, spec.action) for spec in TRANSITIONS]
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_resolution_is_offered_from_exactly_the_in_hand_statuses(self) -> None:
        resolution = [
            spec
            for spec in TRANSITIONS
            if spec.action == ItemAction.RESOLVE_TRANSACTION
        ]
        self.assertEqual({spec.source for spec in resolution}, set(IN_HAND_STATUSES))
        self.assertTrue(all(spec.preempts for spec in resolution))
        self.assertEqual([spec for spec in TRANSITIONS if spec.preempts], resolution)

    def test_targets_match_what_the_lifecycle_actually_writes(self) -> None:
        recorded = {
            (write.source, write.action): write.transaction_status_after
            for write in EXPECTED_WRITES
        }
        ordinary = {
            (spec.source, spec.action): spec.target
            for spec in TRANSITIONS
            if not spec.preempts
        }
        self.assertEqual(ordinary, recorded)
