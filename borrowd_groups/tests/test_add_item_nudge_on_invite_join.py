from typing import Any

from django.test import TestCase
from django.urls import reverse
from notifications.models import Notification

from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_groups.views import InviteSigner
from borrowd_items.models import Item, ItemCategory
from borrowd_notifications.models import NotificationType
from borrowd_users.models import BorrowdUser


class AddItemNudgeOnInviteJoinTests(TestCase):
    """GroupJoinView.post wiring for NotificationService.
    send_add_item_nudge_if_needed() -- the notification-level behavior
    itself is covered by AddItemNudgeNotificationTests in
    borrowd_notifications/tests.py."""

    def setUp(self) -> None:
        self.creator = BorrowdUser.objects.create_user(
            username="creator", email="creator@example.com", password="password"
        )
        self.joiner = BorrowdUser.objects.create_user(
            username="joiner", email="joiner@example.com", password="password"
        )
        self.category = ItemCategory.objects.create(name="Tools")

    def _join_url_for(self, group: BorrowdGroup) -> str:
        encoded = InviteSigner.sign_invite(group.pk, group.name)
        return reverse("borrowd_groups:group-join", kwargs={"encoded": encoded})

    def _create_group(self, *, requires_approval: bool) -> BorrowdGroup:
        return BorrowdGroup.objects.create_group(
            name="A Group",
            created_by=self.creator,
            updated_by=self.creator,
            membership_requires_approval=requires_approval,
        )

    def _nudges(self) -> Any:
        return Notification.objects.filter(
            recipient=self.joiner,
            verb=NotificationType.GROUP_JOINED_NEEDS_ITEM.value,
        )

    def test_auto_accepted_join_sends_nudge_and_sets_flag(self) -> None:
        group = self._create_group(requires_approval=False)

        self.client.force_login(self.joiner)
        self.client.post(self._join_url_for(group))

        self.assertEqual(self._nudges().count(), 1)
        self.joiner.profile.refresh_from_db()
        self.assertTrue(self.joiner.profile.add_item_nudge_sent)

    def test_pending_join_sends_nudge_and_sets_flag(self) -> None:
        group = self._create_group(requires_approval=True)

        self.client.force_login(self.joiner)
        response = self.client.post(self._join_url_for(group))

        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        self.assertEqual(self._nudges().count(), 1)
        self.joiner.profile.refresh_from_db()
        self.assertTrue(self.joiner.profile.add_item_nudge_sent)

    def test_no_nudge_when_user_already_owns_an_item(self) -> None:
        item = Item.objects.create(
            name="Drill",
            description="A description",
            owner=self.joiner,
            created_by=self.joiner,
            updated_by=self.joiner,
        )
        item.categories.add(self.category)
        group = self._create_group(requires_approval=False)

        self.client.force_login(self.joiner)
        self.client.post(self._join_url_for(group))

        self.assertEqual(self._nudges().count(), 0)

    def test_no_second_nudge_when_joining_a_second_group(self) -> None:
        first_group = self._create_group(requires_approval=False)
        second_creator = BorrowdUser.objects.create_user(
            username="creator2", email="creator2@example.com", password="password"
        )
        second_group = BorrowdGroup.objects.create_group(
            name="Second Group",
            created_by=second_creator,
            updated_by=second_creator,
            membership_requires_approval=False,
        )

        self.client.force_login(self.joiner)
        self.client.post(self._join_url_for(first_group))
        self.client.post(self._join_url_for(second_group))

        self.assertEqual(self._nudges().count(), 1)

    def test_existing_redirects_and_messages_unchanged(self) -> None:
        """Confirms the nudge call doesn't alter the pre-existing
        redirect/messages behavior it was inserted next to."""
        group = self._create_group(requires_approval=False)

        self.client.force_login(self.joiner)
        response = self.client.post(self._join_url_for(group))

        membership = Membership.objects.get(user=self.joiner, group=group)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertRedirects(response, reverse("item-list"))
