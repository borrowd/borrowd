"""
Tests for the auto-save-on-select profile photo upload endpoint.

Covers:
- upload_profile_photo_view saving a new/replacement profile photo
- ProfilePhotoUploadForm extension/size validation
- auth/method guards on the endpoint
"""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from borrowd_users.forms import MAX_PROFILE_PHOTO_SIZE_BYTES
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

    def test_upload_rejects_oversized_file(self) -> None:
        self.client.force_login(self.user)
        oversized = create_test_image(size_bytes=MAX_PROFILE_PHOTO_SIZE_BYTES + 1)

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
