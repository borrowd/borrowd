from django.test import TestCase
from django.urls import reverse

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import Item, ItemCategory, Transaction, TransactionStatus
from borrowd_users.models import BorrowdUser


class UsersLeavingGroupsTests(TestCase):
    """
    Tests for the leave-group flow.

    Standard members can leave a group.
    Moderators can leave through this flow.
    Members with actively borrowed items cannot leave.

    Empty groups are deleted when the last active member leaves.
    """

    def setUp(self) -> None:
        # Arrange
        # Create users for the group and transaction.
        self.owner = BorrowdUser.objects.create_user(
            username="owner",
            password="password",
        )
        self.member = BorrowdUser.objects.create_user(
            username="member",
            password="password",
        )
        self.other_user = BorrowdUser.objects.create_user(
            username="other",
            password="password",
        )

        # Create a group where the owner is the default moderator and
        # the member is a standard member.
        self.group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=self.owner,
            updated_by=self.owner,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )
        self.group.add_user(self.member, trust_level=TrustLevel.STANDARD)

    def test_member_can_leave_group(self) -> None:
        # Arrange
        self.client.force_login(self.member)

        # Act
        response = self.client.post(
            reverse("borrowd_groups:leave-group", args=[self.group.pk])
        )

        # Assert
        # The member should be redirected back to the group list and
        # their membership should be removed.
        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        self.assertFalse(
            Membership.objects.filter(user=self.member, group=self.group).exists()
        )

    def test_non_member_cannot_leave_group(self) -> None:
        # Arrange
        self.client.force_login(self.other_user)

        # Act
        response = self.client.post(
            reverse("borrowd_groups:leave-group", args=[self.group.pk])
        )

        # Assert
        # A non-member should not be able to leave a group they do not belong to.
        self.assertRedirects(
            response,
            reverse("borrowd_groups:group-detail", args=[self.group.pk]),
            target_status_code=403,
        )
        self.assertFalse(
            Membership.objects.filter(user=self.other_user, group=self.group).exists()
        )

    def test_moderator_can_leave_group(self) -> None:
        # Arrange
        # The owner is the group's default moderator.
        self.client.force_login(self.owner)

        # Act
        response = self.client.post(
            reverse("borrowd_groups:leave-group", args=[self.group.pk])
        )

        # Assert
        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        self.assertFalse(
            Membership.objects.filter(user=self.owner, group=self.group).exists()
        )

    def test_last_active_member_moderator_leave_deletes_group(self) -> None:
        # Arrange
        solo_owner = BorrowdUser.objects.create_user(
            username="solo_owner",
            password="password",
        )
        solo_group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Solo Group",
            created_by=solo_owner,
            updated_by=solo_owner,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )

        self.client.force_login(solo_owner)

        # Act
        response = self.client.post(
            reverse("borrowd_groups:leave-group", args=[solo_group.pk])
        )

        # Assert
        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        self.assertFalse(
            Membership.objects.filter(user=solo_owner, group=solo_group).exists()
        )
        self.assertFalse(BorrowdGroup.objects.filter(pk=solo_group.pk).exists())

    def test_member_with_active_transaction_in_group_cannot_leave_group(self) -> None:
        # Arrange
        # Create an item and an active transaction involving the member.
        category = ItemCategory.objects.create(
            name="Tools",
            description="Tools category",
        )
        item = Item.objects.create(
            name="Drill",
            description="Cordless drill",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
            trust_level_required=TrustLevel.STANDARD,
        )
        item.categories.add(category)

        Transaction.objects.create(
            item=item,
            party1=self.owner,
            party2=self.member,
            status=TransactionStatus.COLLECTED,
            created_by=self.member,
            updated_by=self.member,
        )

        self.client.force_login(self.member)

        # Act
        response = self.client.post(
            reverse("borrowd_groups:leave-group", args=[self.group.pk])
        )

        # Assert
        # Members with active transactions in the group must stay in the group until
        # those transactions are resolved.
        self.assertRedirects(
            response,
            reverse("borrowd_groups:group-detail", args=[self.group.pk]),
        )
        self.assertTrue(
            Membership.objects.filter(user=self.member, group=self.group).exists()
        )

    def test_member_with_requested_transaction_in_group_can_leave_group(self) -> None:
        # Arrange
        category = ItemCategory.objects.create(
            name="Requested Tools",
            description="Requested tools category",
        )
        item = Item.objects.create(
            name="Hose",
            description="Garden hose",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
            trust_level_required=TrustLevel.STANDARD,
        )
        item.categories.add(category)

        Transaction.objects.create(
            item=item,
            party1=self.owner,
            party2=self.member,
            status=TransactionStatus.REQUESTED,
            created_by=self.member,
            updated_by=self.member,
        )

        self.client.force_login(self.member)

        # Act
        response = self.client.post(
            reverse("borrowd_groups:leave-group", args=[self.group.pk])
        )

        # Assert
        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        self.assertFalse(
            Membership.objects.filter(user=self.member, group=self.group).exists()
        )

    def test_member_with_borrowed_item_and_other_shared_group_can_leave_group(
        self,
    ) -> None:
        # Arrange
        # The member and owner already share self.group.
        # Add a second active shared group so they remain connected
        # even after the member leaves the first group.
        other_shared_group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Second Shared Group",
            created_by=self.owner,
            updated_by=self.owner,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )
        other_shared_group.add_user(self.member, trust_level=TrustLevel.STANDARD)

        category = ItemCategory.objects.create(
            name="Shared Group Tools",
            description="Tools category",
        )
        item = Item.objects.create(
            name="Ladder",
            description="Foldable ladder",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
            trust_level_required=TrustLevel.STANDARD,
        )
        item.categories.add(category)

        Transaction.objects.create(
            item=item,
            party1=self.owner,
            party2=self.member,
            status=TransactionStatus.COLLECTED,
            created_by=self.member,
            updated_by=self.member,
        )

        self.client.force_login(self.member)

        # Act
        response = self.client.post(
            reverse("borrowd_groups:leave-group", args=[self.group.pk])
        )

        # Assert
        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        self.assertFalse(
            Membership.objects.filter(user=self.member, group=self.group).exists()
        )
        self.assertTrue(
            Membership.objects.filter(
                user=self.member,
                group=other_shared_group,
            ).exists()
        )

    def test_member_with_active_transaction_outside_group_can_leave_group(self) -> None:
        # Arrange
        # Create an item owned by a user who is not a member of this group.
        # This transaction is actively borrowed, but it should not count
        # for the group the member is trying to leave.
        category = ItemCategory.objects.create(
            name="Tools Outside Group",
            description="Tools category outside the group",
        )
        item = Item.objects.create(
            name="Saw",
            description="Hand saw",
            owner=self.other_user,
            created_by=self.owner,
            updated_by=self.owner,
            trust_level_required=TrustLevel.STANDARD,
        )
        item.categories.add(category)

        Transaction.objects.create(
            item=item,
            party1=self.other_user,
            party2=self.member,
            status=TransactionStatus.COLLECTED,
            created_by=self.member,
            updated_by=self.member,
        )

        self.client.force_login(self.member)

        # Act
        response = self.client.post(
            reverse("borrowd_groups:leave-group", args=[self.group.pk])
        )

        # Assert
        # The member should still be able to leave this group because
        # the borrowed transaction is not in this group context.
        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        self.assertFalse(
            Membership.objects.filter(user=self.member, group=self.group).exists()
        )

    def test_member_with_active_transaction_in_different_group_can_leave_group(
        self,
    ) -> None:
        # Arrange
        # Create a second group that includes the member and other_user.
        # The active transaction belongs to that shared group context,
        # not to the original group the member is trying to leave.
        other_group = BorrowdGroup.objects.create(
            name="Other Group",
            created_by=self.other_user,
            updated_by=self.other_user,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )
        other_group.add_user(self.member, trust_level=TrustLevel.STANDARD)

        category = ItemCategory.objects.create(
            name="Other Group Tools",
            description="Tools category in another group context",
        )
        item = Item.objects.create(
            name="Ladder",
            description="Foldable ladder",
            owner=self.other_user,
            created_by=self.owner,
            updated_by=self.owner,
            trust_level_required=TrustLevel.STANDARD,
        )
        item.categories.add(category)

        Transaction.objects.create(
            item=item,
            party1=self.other_user,
            party2=self.member,
            status=TransactionStatus.REQUESTED,
            created_by=self.member,
            updated_by=self.member,
        )

        self.client.force_login(self.member)

        # Act
        response = self.client.post(
            reverse("borrowd_groups:leave-group", args=[self.group.pk])
        )

        # Assert
        # The member should be able to leave the original group because
        # the active transaction belongs to a different shared group context.
        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        self.assertFalse(
            Membership.objects.filter(user=self.member, group=self.group).exists()
        )
        self.assertTrue(
            Membership.objects.filter(user=self.member, group=other_group).exists()
        )
