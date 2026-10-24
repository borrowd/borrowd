from django.test import TestCase
from django.urls import reverse

from borrowd_users.models import BorrowdUser


class OnboardingStepLinksTests(TestCase):
    """Each step's Back/Continue links use {% url %}, not a hardcoded path --
    see CON-03 from the UX audit."""

    def setUp(self) -> None:
        user = BorrowdUser.objects.create_user(
            username="onboarder", email="onboarder@example.com", password="password"
        )
        self.client.force_login(user)

    def test_step2_continue_link_uses_the_named_url(self) -> None:
        response = self.client.get(reverse("onboarding_step2"))

        self.assertContains(response, f'href="{reverse("onboarding_step3")}"')
        self.assertNotContains(response, 'href="/onboarding/3"')
