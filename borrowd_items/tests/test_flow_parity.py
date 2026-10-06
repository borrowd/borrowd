"""The hand-written action rules and the transition table must agree."""

from datetime import timedelta
from itertools import product
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from borrowd_items import flow_parity
from borrowd_items.flow import available_actions
from borrowd_items.flow_parity import (
    ACTIONS_DIFFER,
    LENDER_IS_NOT_OWNER,
    actions_for_open_transaction,
    comparison_counts,
    legacy_actions_for,
)
from borrowd_items.models import (
    OPEN_TRANSACTION_STATUSES,
    Item,
    ItemAction,
    ItemStatus,
    Transaction,
    TransactionStatus,
)
from borrowd_items.tests.test_flow import BORROWER, LENDER, NOW, WAIT, FlowTestCase
from borrowd_users.models import BorrowdUser

# Exercise production reporting instead of raising on disagreement.
deployed = override_settings(DEBUG=False, IS_RUNNING_MANAGE_PY_TESTS=False)


class ParityTestCase(FlowTestCase):
    def setUp(self) -> None:
        super().setUp()
        flow_parity._reported_until.clear()
        flow_parity._comparisons.clear()


class ParityGridTests(ParityTestCase):
    def test_table_agrees_with_the_hand_written_rules_for_every_party_state(
        self,
    ) -> None:
        compared = 0
        for status, role, last_actor, wait_elapsed, counterparty_active in product(
            OPEN_TRANSACTION_STATUSES,
            (LENDER, BORROWER),
            (LENDER, BORROWER),
            (True, False),
            (True, False),
        ):
            with self.subTest(
                status=status.name,
                role=role,
                last_actor=last_actor,
                wait_elapsed=wait_elapsed,
                counterparty_active=counterparty_active,
            ):
                self.other(role).is_active = counterparty_active
                requested_at = (
                    NOW - WAIT + (timedelta() if wait_elapsed else timedelta(seconds=1))
                )
                tx = self.transaction(
                    status,
                    updated_by=self.party(last_actor),
                    return_requested_at=requested_at,
                )
                actor = self.party(role)
                self.assertEqual(
                    available_actions(tx, actor, now=NOW),
                    legacy_actions_for(self.item, tx, actor, now=NOW),
                )
                self.other(role).is_active = True
                compared += 1
        self.assertEqual(compared, 9 * 2 * 2 * 2 * 2)


class LenderIsNotOwnerTests(ParityTestCase):
    """The Item's owner was changed under an open Transaction."""

    def setUp(self) -> None:
        super().setUp()
        self.item.owner = self.bystander
        self.tx = self.transaction(
            TransactionStatus.REQUESTED, updated_by=self.borrower
        )

    def test_the_table_still_treats_party1_as_the_lender(self) -> None:
        self.assertEqual(
            available_actions(self.tx, self.lender, now=NOW),
            (ItemAction.REJECT_REQUEST, ItemAction.ACCEPT_REQUEST),
        )
        self.assertEqual(
            legacy_actions_for(self.item, self.tx, self.lender, now=NOW),
            (ItemAction.CANCEL_REQUEST,),
        )

    def test_it_is_reported_as_inconsistent_data_not_as_a_wrong_table(self) -> None:
        with self.assertRaisesRegex(AssertionError, LENDER_IS_NOT_OWNER):
            actions_for_open_transaction(self.item, self.tx, self.lender)


class DivergenceUnderTestTests(ParityTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tx = self.transaction(
            TransactionStatus.REQUESTED, updated_by=self.borrower
        )
        self.expected = (ItemAction.REJECT_REQUEST, ItemAction.ACCEPT_REQUEST)

    def test_agreement_returns_the_served_actions(self) -> None:
        self.assertEqual(
            actions_for_open_transaction(self.item, self.tx, self.lender),
            self.expected,
        )

    def test_a_disagreement_fails_the_test_that_caused_it(self) -> None:
        with mock.patch.object(
            flow_parity, "available_actions", return_value=(ItemAction.CANCEL_REQUEST,)
        ):
            with self.assertRaisesRegex(AssertionError, ACTIONS_DIFFER):
                actions_for_open_transaction(self.item, self.tx, self.lender)

    def test_an_error_in_the_table_fails_the_test_too(self) -> None:
        with mock.patch.object(flow_parity, "available_actions", side_effect=KeyError):
            with self.assertRaises(KeyError):
                actions_for_open_transaction(self.item, self.tx, self.lender)

    @override_settings(ITEMS_FLOW_PARITY_CHECK=False)
    def test_switched_off_the_table_is_not_consulted(self) -> None:
        with mock.patch.object(flow_parity, "available_actions") as table:
            self.assertEqual(
                actions_for_open_transaction(self.item, self.tx, self.lender),
                self.expected,
            )
        table.assert_not_called()

    def test_both_rule_sets_are_given_the_same_captured_time(self) -> None:
        with (
            mock.patch("borrowd_items.flow_parity.timezone.now", return_value=NOW),
            mock.patch.object(
                flow_parity, "legacy_actions_for", return_value=()
            ) as legacy,
            mock.patch.object(
                flow_parity, "available_actions", return_value=()
            ) as table,
        ):
            actions_for_open_transaction(self.item, self.tx, self.lender)
        self.assertIs(legacy.call_args.kwargs["now"], NOW)
        self.assertIs(table.call_args.kwargs["now"], NOW)


@deployed
class DivergenceWhenDeployedTests(ParityTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tx = self.transaction(
            TransactionStatus.REQUESTED, updated_by=self.borrower
        )
        self.served = (ItemAction.REJECT_REQUEST, ItemAction.ACCEPT_REQUEST)
        self.wrong = (ItemAction.CANCEL_REQUEST,)

    def test_the_hand_written_answer_is_served_and_the_difference_reported(
        self,
    ) -> None:
        with (
            mock.patch.object(
                flow_parity, "available_actions", return_value=self.wrong
            ),
            mock.patch(
                "borrowd_items.flow_parity.sentry_sdk.capture_message"
            ) as capture,
        ):
            answer = actions_for_open_transaction(self.item, self.tx, self.lender)
        self.assertEqual(answer, self.served)
        capture.assert_called_once()
        self.assertIn(ACTIONS_DIFFER, capture.call_args.args[0])
        self.assertEqual(capture.call_args.kwargs["level"], "error")

    def test_a_changed_owner_is_reported_under_its_own_label(self) -> None:
        self.item.owner = self.bystander
        with mock.patch(
            "borrowd_items.flow_parity.sentry_sdk.capture_message"
        ) as capture:
            answer = actions_for_open_transaction(self.item, self.tx, self.lender)
        self.assertEqual(answer, (ItemAction.CANCEL_REQUEST,))
        self.assertIn(LENDER_IS_NOT_OWNER, capture.call_args.args[0])

    def test_one_shape_of_divergence_is_reported_once(self) -> None:
        with (
            mock.patch.object(
                flow_parity, "available_actions", return_value=self.wrong
            ),
            mock.patch(
                "borrowd_items.flow_parity.sentry_sdk.capture_message"
            ) as capture,
        ):
            for _ in range(25):
                actions_for_open_transaction(self.item, self.tx, self.lender)
            self.assertEqual(capture.call_count, 1)
            # A different status gets a separate report.
            accepted = self.transaction(
                TransactionStatus.ACCEPTED, updated_by=self.lender
            )
            actions_for_open_transaction(self.item, accepted, self.lender)
            self.assertEqual(capture.call_count, 2)

    def test_a_shape_is_reported_again_once_its_hour_is_up(self) -> None:
        clock = mock.patch(
            "borrowd_items.flow_parity.time.monotonic", return_value=1000.0
        )
        with (
            mock.patch.object(
                flow_parity, "available_actions", return_value=self.wrong
            ),
            mock.patch(
                "borrowd_items.flow_parity.sentry_sdk.capture_message"
            ) as capture,
            clock as monotonic,
        ):
            actions_for_open_transaction(self.item, self.tx, self.lender)
            monotonic.return_value += flow_parity._REPORT_TTL_SECONDS - 1
            actions_for_open_transaction(self.item, self.tx, self.lender)
            self.assertEqual(capture.call_count, 1)
            monotonic.return_value += 2
            actions_for_open_transaction(self.item, self.tx, self.lender)
            self.assertEqual(capture.call_count, 2)

    def test_the_report_cache_stays_bounded(self) -> None:
        for n in range(flow_parity._REPORT_CACHE_SIZE * 3):
            self.assertTrue(flow_parity._should_report(("shape", n)))
            self.assertLessEqual(
                len(flow_parity._reported_until), flow_parity._REPORT_CACHE_SIZE
            )

    def test_an_error_in_the_table_never_reaches_the_user(self) -> None:
        with (
            mock.patch.object(flow_parity, "available_actions", side_effect=KeyError),
            mock.patch(
                "borrowd_items.flow_parity.sentry_sdk.capture_exception"
            ) as capture,
        ):
            answer = actions_for_open_transaction(self.item, self.tx, self.lender)
        self.assertEqual(answer, self.served)
        capture.assert_called_once()

    def test_each_compared_combination_is_counted_and_logged_once(self) -> None:
        with self.assertLogs("borrowd.items.flow_parity", level="INFO") as logs:
            for _ in range(3):
                actions_for_open_transaction(self.item, self.tx, self.lender)
            actions_for_open_transaction(self.item, self.tx, self.borrower)
        self.assertEqual(
            comparison_counts(),
            {
                ("REQUESTED", "lender", self.served): 3,
                ("REQUESTED", "borrower", (ItemAction.CANCEL_REQUEST,)): 1,
            },
        )
        self.assertEqual(len(logs.records), 2)


class ItemUsesTheShadowTests(TestCase):
    def test_get_actions_for_serves_the_shadowed_answer_for_a_party(self) -> None:
        lender = BorrowdUser.objects.create_user(
            username="fp_lender", email="fp_lender@example.com", password="password"
        )
        borrower = BorrowdUser.objects.create_user(
            username="fp_borrower", email="fp_borrower@example.com", password="password"
        )
        item = Item.objects.create(
            name="Drill",
            description="A useful thing",
            owner=lender,
            status=ItemStatus.REQUESTED,
            created_by=lender,
            updated_by=lender,
        )
        tx = Transaction.objects.create(
            item=item,
            party1=lender,
            party2=borrower,
            status=TransactionStatus.REQUESTED,
            created_by=borrower,
            updated_by=borrower,
        )
        with mock.patch(
            "borrowd_items.models.actions_for_open_transaction",
            return_value=(ItemAction.CANCEL_REQUEST,),
        ) as shadow:
            self.assertEqual(
                item.get_actions_for(borrower), (ItemAction.CANCEL_REQUEST,)
            )
        self.assertEqual(shadow.call_args.args, (item, tx, borrower))


class EveryComparisonNeedsNoDatabase(SimpleTestCase):
    """The comparison must add no queries to a page that renders many cards."""

    def test_comparing_loaded_parties_runs_no_queries(self) -> None:
        lender = BorrowdUser(pk=1, username="lender", is_active=True)
        borrower = BorrowdUser(pk=2, username="borrower", is_active=False)
        item = Item(pk=1, owner=lender)
        tx = Transaction(
            item=item,
            party1=lender,
            party2=borrower,
            status=TransactionStatus.COLLECTED,
            updated_by=borrower,
        )
        # SimpleTestCase fails if the comparison queries the database.
        self.assertEqual(
            actions_for_open_transaction(item, tx, lender),
            (ItemAction.RESOLVE_TRANSACTION,),
        )
