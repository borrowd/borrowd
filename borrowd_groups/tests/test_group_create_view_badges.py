from django.test import TestCase
from django.urls import reverse

from borrowd_badges.models import Badge, UserBadge
from borrowd_badges.services import LOCAL_ACTIVIST_SLUG
from borrowd_users.models import BorrowdUser


class GroupCreateViewLocalActivistBadgeTests(TestCase):
    """Confirms GroupCreateView.form_valid actually wires up
    award_local_activist_if_needed -- the unit-level behavior of that award
    itself is covered in borrowd_badges.tests.
    """

    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="organizer", email="organizer@example.com", password="password"
        )
        Badge.objects.create(slug=LOCAL_ACTIVIST_SLUG, name="Local Activist")

    def _earned(self) -> bool:
        return UserBadge.objects.filter(
            user=self.user, badge__slug=LOCAL_ACTIVIST_SLUG
        ).exists()

    def test_second_group_awards_the_badge(self) -> None:
        self.client.force_login(self.user)

        self.client.post(
            reverse("borrowd_groups:group-create"),
            {
                "name": "First Group",
                "description": "First",
                "membership_requires_approval": False,
            },
        )
        self.assertFalse(self._earned())

        self.client.post(
            reverse("borrowd_groups:group-create"),
            {
                "name": "Second Group",
                "description": "Second",
                "membership_requires_approval": False,
            },
        )

        self.assertTrue(self._earned())
