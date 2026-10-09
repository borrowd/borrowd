"""
Tests for the badges section on both the editable profile page (labeled
"My badges", beneath "Personal information") and the public profile page
(labeled "Badges", under the bio).
"""

from django.test import TestCase
from django.urls import reverse

from borrowd_badges.models import Badge, UserBadge
from borrowd_groups.models import BorrowdGroup
from borrowd_users.models import BorrowdUser


class ProfilePageBadgesTests(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="rowan", email="rowan@example.com", password="hunter22!"
        )
        self.client.force_login(self.user)

    def test_no_badges_section_when_no_badges_are_preloaded(self) -> None:
        response = self.client.get(reverse("profile"))

        self.assertNotContains(response, "My badges")

    def test_shows_the_grayscale_icon_for_an_unearned_badge(self) -> None:
        Badge.objects.create(slug="trophy", name="Trophy")

        response = self.client.get(reverse("profile"))

        self.assertContains(response, "My badges")
        self.assertContains(response, "badges/trophy-gray.png")
        self.assertNotContains(response, "badges/trophy.png")

    def test_shows_the_color_icon_for_an_earned_badge(self) -> None:
        badge = Badge.objects.create(slug="trophy", name="Trophy")
        UserBadge.objects.create(user=self.user, badge=badge)

        response = self.client.get(reverse("profile"))

        self.assertContains(response, "badges/trophy.png")

    def test_my_badges_appears_after_personal_information(self) -> None:
        Badge.objects.create(slug="trophy", name="Trophy")

        response = self.client.get(reverse("profile"))

        content = response.content.decode()
        self.assertLess(
            content.index("Personal information"), content.index("My badges")
        )


class PublicProfilePageBadgesTests(TestCase):
    def setUp(self) -> None:
        self.viewer = BorrowdUser.objects.create_user(
            username="viewer", email="viewer@example.com", password="password"
        )
        self.subject = BorrowdUser.objects.create_user(
            username="subject", email="subject@example.com", password="password"
        )
        group = BorrowdGroup.objects.create_group(
            name="Shared",
            created_by=self.viewer,
            updated_by=self.viewer,
            membership_requires_approval=False,
        )
        group.add_user(self.subject)
        self.client.force_login(self.viewer)

    def test_no_badges_subheading_when_no_badges_are_preloaded(self) -> None:
        response = self.client.get(reverse("public-profile", args=[self.subject.pk]))

        self.assertNotContains(response, "Badges")

    def test_shows_the_grayscale_icon_for_an_unearned_badge(self) -> None:
        Badge.objects.create(slug="trophy", name="Trophy")

        response = self.client.get(reverse("public-profile", args=[self.subject.pk]))

        self.assertContains(response, "Badges")
        self.assertContains(response, "badges/trophy-gray.png")

    def test_shows_the_color_icon_for_a_badge_the_subject_has_earned(self) -> None:
        badge = Badge.objects.create(slug="trophy", name="Trophy")
        UserBadge.objects.create(user=self.subject, badge=badge)

        response = self.client.get(reverse("public-profile", args=[self.subject.pk]))

        self.assertContains(response, "badges/trophy.png")
