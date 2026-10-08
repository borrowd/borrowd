"""
Tests for the auto-save-on-select profile photo upload endpoint.

Covers:
- upload_profile_photo_view saving a new/replacement profile photo
- ProfilePhotoUploadForm extension/size validation
- auth/method guards on the endpoint
"""

from io import BytesIO
from typing import Any

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from notifications.models import Notification
from PIL import Image

from borrowd.validators import MAX_PHOTO_SIZE_BYTES
from borrowd_groups.models import BorrowdGroup
from borrowd_notifications.models import NotificationType
from borrowd_users.models import BorrowdUser


def create_test_image(
    size_bytes: int | None = None,
    format: str = "JPEG",
    filename: str = "photo.jpg",
    content_type: str = "image/jpeg",
) -> SimpleUploadedFile:
    image = Image.new("RGB", (100, 100), color="blue")
    buffer = BytesIO()
    image.save(buffer, format=format)

    if size_bytes is not None and size_bytes > buffer.tell():
        buffer.write(b"\x00" * (size_bytes - buffer.tell()))

    buffer.seek(0)
    return SimpleUploadedFile(filename, buffer.read(), content_type=content_type)


class UploadProfilePhotoViewTests(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="photo_uploader",
            email="photo_uploader@example.com",
            password="password",
        )
        self.url = reverse("profile-upload-photo")

    def test_upload_saves_image_and_returns_url(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(self.url, {"image": create_test_image()})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.image)
        self.assertEqual(data["image_url"], self.user.profile.image.url)

    def test_upload_replaces_existing_image(self) -> None:
        self.client.force_login(self.user)
        self.client.post(self.url, {"image": create_test_image(filename="first.jpg")})
        self.user.profile.refresh_from_db()
        first_image_name = self.user.profile.image.name

        response = self.client.post(
            self.url, {"image": create_test_image(filename="second.jpg")}
        )

        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertNotEqual(self.user.profile.image.name, first_image_name)

    def test_upload_replaces_existing_image_removes_old_file_from_storage(
        self,
    ) -> None:
        self.client.force_login(self.user)
        self.client.post(self.url, {"image": create_test_image(filename="first.jpg")})
        self.user.profile.refresh_from_db()
        first_image_name = self.user.profile.image.name

        # django-cleanup removes the replaced file via transaction.on_commit,
        # which TestCase's wrapping transaction never fires on its own.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.url, {"image": create_test_image(filename="second.jpg")}
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(default_storage.exists(first_image_name))

    def test_upload_rejects_disallowed_extension(self) -> None:
        self.client.force_login(self.user)
        bad_file = SimpleUploadedFile(
            "notes.txt", b"not an image", content_type="text/plain"
        )

        response = self.client.post(self.url, {"image": bad_file})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.image)

    def test_upload_rejects_non_image_content_with_allowed_extension(self) -> None:
        """A file whose name carries an allowed extension but isn't actually
        an image (e.g. renamed/corrupted) must still be rejected -- the
        extension allowlist alone doesn't validate file content."""
        self.client.force_login(self.user)
        spoofed_file = SimpleUploadedFile(
            "photo.jpg", b"not actually an image", content_type="image/jpeg"
        )

        response = self.client.post(self.url, {"image": spoofed_file})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.image)

    def test_upload_rejects_oversized_file(self) -> None:
        self.client.force_login(self.user)
        oversized = create_test_image(size_bytes=MAX_PHOTO_SIZE_BYTES + 1)

        response = self.client.post(self.url, {"image": oversized})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.image)

    def test_upload_requires_login(self) -> None:
        response = self.client.post(self.url, {"image": create_test_image()})

        self.assertEqual(response.status_code, 302)

    def test_upload_requires_post(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)


class UploadProfilePhotoViewInviteFriendsNudgeTests(TestCase):
    """Confirms upload_profile_photo_view actually wires up
    NotificationService.send_invite_friends_nudge_if_needed -- the
    unit-level behavior of that nudge itself is covered in
    borrowd_notifications.tests.InviteFriendsNudgeNotificationTests.
    """

    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="uploader", email="uploader@example.com", password="password"
        )
        self.url = reverse("profile-upload-photo")

    def _nudges(self) -> Any:
        return Notification.objects.filter(
            recipient=self.user,
            verb=NotificationType.PHOTO_ADDED_NEEDS_INVITES.value,
        )

    def test_user_with_a_group_is_nudged_after_adding_a_photo(self) -> None:
        BorrowdGroup.objects.create_group(
            name="Book Club",
            created_by=self.user,
            updated_by=self.user,
            membership_requires_approval=False,
        )
        self.client.force_login(self.user)

        self.client.post(self.url, {"image": create_test_image()})

        self.assertEqual(self._nudges().count(), 1)

    def test_user_without_a_group_is_not_nudged(self) -> None:
        self.client.force_login(self.user)

        self.client.post(self.url, {"image": create_test_image()})

        self.assertEqual(self._nudges().count(), 0)


class ProfilePhotoUploadBellRefreshTests(TestCase):
    """The upload is a plain fetch, not an htmx request, so the server can't
    append an out-of-band bell refresh to its JSON response the way other
    actions do. Without the profile page dispatching this event itself, a
    notification created by the upload (e.g. the "invite friends" nudge)
    would sit unseen until the bell's next 30s poll or a page load."""

    def test_successful_upload_dispatches_a_bell_refresh_event(self) -> None:
        user = BorrowdUser.objects.create_user(
            username="uploader", email="uploader@example.com", password="password"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("profile"))

        self.assertContains(
            response, "document.dispatchEvent(new CustomEvent('notifications:refresh'))"
        )
