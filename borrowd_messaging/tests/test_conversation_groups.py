from django.utils import timezone

from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_items.models import Item
from borrowd_messaging.exceptions import (
    ConversationGroupSelectionRequired,
    InvalidConversationGroup,
)
from borrowd_messaging.services import MessagingService
from borrowd_messaging.tests.base import MessagingTestCase


class ConversationGroupResolutionTests(MessagingTestCase):
    def _make_eligible_group(self, name: str) -> BorrowdGroup:
        group = self.make_group(name=name)
        group.add_user(self.borrower)
        return group

    def test_eligible_groups_apply_every_context_rule(self) -> None:
        eligible = self._make_eligible_group("Eligible")

        pending_borrower = self.make_group(
            name="Pending borrower",
            membership_requires_approval=True,
        )
        pending_borrower.add_user(self.borrower)

        other_moderator = self.make_user("other-moderator")
        inactive_lender = self.make_group(
            name="Inactive lender",
            created_by=other_moderator,
            updated_by=other_moderator,
        )
        inactive_lender.add_user(self.lender)
        inactive_lender.add_user(self.borrower)
        lender_membership = Membership.objects.get(
            group=inactive_lender,
            user=self.lender,
        )
        lender_membership.status = MembershipStatus.SUSPENDED
        lender_membership.save(update_fields=["status"])

        soft_deleted = self._make_eligible_group("Soft deleted")
        soft_deleted.deleted_at = timezone.now()
        soft_deleted.deleted_by = self.lender
        soft_deleted.save(update_fields=["deleted_at", "deleted_by"])

        missing_permissions_group = self._make_eligible_group(
            "Missing permissions group"
        )
        BorrowdGroup.objects.filter(pk=missing_permissions_group.pk).update(
            perms_group=None
        )

        not_shared = self._make_eligible_group("Not shared")

        self.item.share_with_all_groups = False
        self.item.save(update_fields=["share_with_all_groups"])
        self.item.shared_with_groups.add(
            eligible,
            pending_borrower,
            inactive_lender,
            soft_deleted,
            missing_permissions_group,
        )

        groups = list(
            MessagingService.eligible_conversation_groups(
                self.borrower,
                self.item,
            )
        )

        self.assertEqual(groups, [eligible])
        self.assertNotIn(not_shared, groups)

    def test_eligible_groups_use_one_query_with_an_uncached_owner(self) -> None:
        eligible = self._make_eligible_group("Eligible")
        item = Item.objects.get(pk=self.item.pk)

        with self.assertNumQueries(1):
            groups = list(
                MessagingService.eligible_conversation_groups(
                    self.borrower,
                    item,
                )
            )

        self.assertEqual(groups, [eligible])

    def test_no_eligible_group_resolves_to_unfiled(self) -> None:
        group = MessagingService.resolve_conversation_group(
            self.borrower,
            self.item,
        )

        self.assertIsNone(group)

    def test_only_eligible_group_is_selected_automatically(self) -> None:
        eligible = self._make_eligible_group("Tool Library")

        group = MessagingService.resolve_conversation_group(
            self.borrower,
            self.item,
        )

        self.assertEqual(group, eligible)

    def test_multiple_eligible_groups_require_a_selection(self) -> None:
        self._make_eligible_group("Group A")
        self._make_eligible_group("Group B")

        with self.assertRaises(ConversationGroupSelectionRequired):
            MessagingService.resolve_conversation_group(
                self.borrower,
                self.item,
            )

    def test_explicit_eligible_group_is_selected(self) -> None:
        self._make_eligible_group("Group A")
        selected = self._make_eligible_group("Group B")

        group = MessagingService.resolve_conversation_group(
            self.borrower,
            self.item,
            selected_group=selected,
        )

        self.assertEqual(group, selected)

    def test_explicit_ineligible_group_is_rejected(self) -> None:
        ineligible = self.make_group(name="Lender only")

        with self.assertRaises(InvalidConversationGroup):
            MessagingService.resolve_conversation_group(
                self.borrower,
                self.item,
                selected_group=ineligible,
            )

    def test_ambiguous_automatic_resolution_can_remain_unfiled(self) -> None:
        self._make_eligible_group("Group A")
        self._make_eligible_group("Group B")

        group = MessagingService.resolve_conversation_group(
            self.borrower,
            self.item,
            require_selection=False,
        )

        self.assertIsNone(group)


class RequestGroupChoicesForItemsTests(MessagingTestCase):
    def _make_eligible_group(self, name: str) -> BorrowdGroup:
        group = self.make_group(name=name)
        group.add_user(self.borrower)
        return group

    def test_batches_ambiguous_choices_by_item(self) -> None:
        group_b = self._make_eligible_group("Group B")
        group_a = self._make_eligible_group("Group A")
        group_c = self._make_eligible_group("Group C")
        explicit_item = self.make_item(
            name="Explicit item",
            share_with_all_groups=False,
        )
        explicit_item.shared_with_groups.add(group_b, group_c)
        single_group_item = self.make_item(
            name="Single-group item",
            share_with_all_groups=False,
        )
        single_group_item.shared_with_groups.add(group_a)

        with self.assertNumQueries(4):
            choices = MessagingService.request_group_choices_for_items(
                self.borrower,
                [self.item, explicit_item, single_group_item],
            )

        self.assertEqual(choices[self.item.pk], (group_a, group_b, group_c))
        self.assertEqual(choices[explicit_item.pk], (group_b, group_c))
        self.assertNotIn(single_group_item.pk, choices)

    def test_existing_thread_does_not_need_another_choice(self) -> None:
        self._make_eligible_group("Group A")
        self._make_eligible_group("Group B")
        self.make_thread()

        choices = MessagingService.request_group_choices_for_items(
            self.borrower,
            [self.item],
        )

        self.assertEqual(choices, {})
