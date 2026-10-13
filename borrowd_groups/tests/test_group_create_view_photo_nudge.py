from typing import Any

from django.test import TestCase
from django.urls import reverse
from notifications.models import Notification

from borrowd_notifications.models import NotificationType
from borrowd_users.models import BorrowdUser, Profile


class GroupCreateViewPhotoNudgeTests(TestCase):
    """Confirms GroupCreateView.form_valid actually wires up
    NotificationService.send_add_profile_photo_nudge_if_needed -- the
    unit-level behavior of that nudge itself is covered in
    borrowd_notifications.tests.AddProfilePhotoNudgeNotificationTests.
    """

    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="creator", email="creator@example.com", password="password"
        )

    def _nudges(self) -> Any:
        return Notification.objects.filter(
            recipient=self.user,
            verb=NotificationType.GROUP_CREATED_NEEDS_PHOTO.value,
        )

    def test_photoless_user_is_nudged_after_creating_a_group(self) -> None:
        self.client.force_login(self.user)

        self.client.post(
            reverse("borrowd_groups:group-create"),
            {
                "name": "Book Club",
                "description": "Readers unite",
                "membership_requires_approval": False,
            },
        )

        self.assertEqual(self._nudges().count(), 1)

    def test_user_with_a_profile_photo_is_not_nudged(self) -> None:
        Profile.objects.filter(user=self.user).update(image="profile_pics/me.jpg")
        self.client.force_login(self.user)

        self.client.post(
            reverse("borrowd_groups:group-create"),
            {
                "name": "Book Club",
                "description": "Readers unite",
                "membership_requires_approval": False,
            },
        )

        self.assertEqual(self._nudges().count(), 0)
