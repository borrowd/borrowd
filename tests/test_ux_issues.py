"""
Tests for issues #366, #387, #388.

Note: Issue #366 sub-item (3) — pre-populated trust level on GroupJoinForm —
is tracked separately in issue #345 and is not implemented here.
"""

from django.test import TestCase
from django.urls import reverse

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_users.models import BorrowdUser


class Issue387ButtonTextConsistencyTest(TestCase):
    """
    Issue #387: 'Mark Picked Up' → 'Confirm picked up' on Item Details.

    Verifies at template level by loading the detail page for a user with
    an accepted transaction (MARK_COLLECTED action available) and confirming
    the rendered HTML contains the correct label.
    """

    databases = "__all__"

    def setUp(self) -> None:
        self.lender = BorrowdUser.objects.create_user(
            username="lender387", email="lender387@example.com", password="pw"
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="borrower387", email="borrower387@example.com", password="pw"
        )
        self.group = BorrowdGroup.objects.create(
            name="Issue387 Group",
            created_by=self.lender,
            updated_by=self.lender,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        self.group.add_user(self.borrower, trust_level=TrustLevel.HIGH)
        from borrowd_items.models import Item, ItemAction

        self.item = Item.objects.create(
            name="Item387",
            description="desc",
            owner=self.lender,
            trust_level_required=TrustLevel.STANDARD,
        )
        # Simulate borrower requesting and lender accepting → MARK_COLLECTED available
        self.item.process_action(user=self.borrower, action=ItemAction.REQUEST_ITEM)
        self.item.process_action(user=self.lender, action=ItemAction.ACCEPT_REQUEST)
        self.client.login(username="borrower387", password="pw")

    def tearDown(self) -> None:
        for tx in self.item.transactions.all():
            tx.delete()
        self.item.delete()
        self.group.delete()
        self.lender.delete()
        self.borrower.delete()

    def test_mark_collected_button_renders_confirm_picked_up(self) -> None:
        """
        The 'MARK_COLLECTED' action button on the Item Detail page
        must display 'Confirm picked up', not 'Mark Collected' or 'Mark Picked Up'.
        """
        response = self.client.get(reverse("item-detail", args=[self.item.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Confirm picked up", content)
        self.assertNotIn("Mark Collected", content)
        self.assertNotIn("Mark Picked Up", content)


class Issue388LogoLinkTest(TestCase):
    """
    Issue #388: Logged-in users clicking the Borrow'd logo should go to
    the item search page (/items/), not the landing page.
    """

    databases = "__all__"

    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="user388", email="user388@example.com", password="pw"
        )

    def tearDown(self) -> None:
        self.user.delete()

    def test_authenticated_header_logo_links_to_item_list(self) -> None:
        """When logged in, the header logo href must point to item-list."""
        self.client.login(username="user388", password="pw")
        response = self.client.get(reverse("item-list"))
        self.assertEqual(response.status_code, 200)
        item_list_url = reverse("item-list")
        self.assertIn(f'href="{item_list_url}"', response.content.decode())

    def test_anonymous_header_logo_does_not_link_to_item_list(self) -> None:
        """
        The navbar (header.html) is only rendered for authenticated users.
        The login page must not link to item-list (a protected route).
        """
        item_list_url = reverse("item-list")
        response = self.client.get(reverse("account_login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(f'href="{item_list_url}"', response.content.decode())


class Issue366OnboardingBackNavigationTest(TestCase):
    """
    Issue #366 sub-items (1) & (2):
    (1) Onboarding step2 and step3 must have a 'Back' navigation link.
    (2) Step3 CTA button must read 'Get started' (sentence case, not 'Get Started').

    Sub-item (3) — GroupJoinForm trust level pre-population — is deferred to #345.
    """

    databases = "__all__"

    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="user366", email="user366@example.com", password="pw"
        )
        self.client.login(username="user366", password="pw")

    def tearDown(self) -> None:
        self.user.delete()

    def test_step2_contains_back_link_to_step1(self) -> None:
        response = self.client.get(reverse("onboarding_step2"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("/onboarding/1", content)
        self.assertIn("Back", content)

    def test_step3_contains_back_link_to_step2(self) -> None:
        response = self.client.get(reverse("onboarding_step3"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("/onboarding/2", content)
        self.assertIn("Back", content)

    def test_step3_cta_is_sentence_case(self) -> None:
        """Button must read 'Get started', not 'Get Started'."""
        response = self.client.get(reverse("onboarding_step3"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Get started", content)
        self.assertNotIn("Get Started", content)
