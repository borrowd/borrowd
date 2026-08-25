from io import BytesIO
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from borrowd.validators import MAX_IMAGE_PIXELS, MAX_PHOTO_SIZE_BYTES
from borrowd_users.forms import ProfileUpdateForm
from borrowd_users.models import BorrowdUser


def create_test_image(size_bytes: int, format: str = "JPEG") -> BytesIO:
    """Create a test image in memory, padded to approximately size_bytes."""
    image = Image.new("RGB", (100, 100), color="green")
    buffer = BytesIO()
    image.save(buffer, format=format)
    current_size = buffer.tell()
    if size_bytes > current_size:
        buffer.write(b"\x00" * (size_bytes - current_size))
    buffer.seek(0)
    return buffer


def create_oversized_dimension_image() -> BytesIO:
    """A solid-color PNG that's tiny in bytes but decodes to far more pixels
    than MAX_IMAGE_PIXELS -- the byte-size check alone would let this through."""
    width = 10000
    height = (MAX_IMAGE_PIXELS * 3) // width
    image = Image.new("RGB", (width, height), color="green")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


class ProfileImageSizeValidationTests(TestCase):
    user: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = BorrowdUser.objects.create_user(
            username="profileowner",
            email="profileowner@example.com",
            password="password",
            first_name="Test",
            last_name="User",
        )

    def get_valid_form_data(self) -> dict[str, Any]:
        return {
            "first_name": "Test",
            "last_name": "User",
            "email": self.user.email,
            "bio": "",
        }

    def test_form_valid_without_image(self) -> None:
        form = ProfileUpdateForm(
            data=self.get_valid_form_data(), instance=self.user.profile
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_valid_with_image_at_size_limit(self) -> None:
        image_data = create_test_image(MAX_PHOTO_SIZE_BYTES)
        uploaded_file = SimpleUploadedFile(
            name="avatar.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )
        form = ProfileUpdateForm(
            data=self.get_valid_form_data(),
            files={"image": uploaded_file},
            instance=self.user.profile,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_invalid_with_oversized_image(self) -> None:
        image_data = create_test_image(MAX_PHOTO_SIZE_BYTES + 1)
        uploaded_file = SimpleUploadedFile(
            name="avatar.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )
        form = ProfileUpdateForm(
            data=self.get_valid_form_data(),
            files={"image": uploaded_file},
            instance=self.user.profile,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_form_invalid_with_oversized_dimensions(self) -> None:
        image_data = create_oversized_dimension_image()
        content = image_data.read()
        self.assertLess(len(content), MAX_PHOTO_SIZE_BYTES)

        uploaded_file = SimpleUploadedFile(
            name="avatar.png",
            content=content,
            content_type="image/png",
        )
        form = ProfileUpdateForm(
            data=self.get_valid_form_data(),
            files={"image": uploaded_file},
            instance=self.user.profile,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_form_invalid_with_disallowed_extension(self) -> None:
        uploaded_file = SimpleUploadedFile(
            name="avatar.gif",
            content=b"not a real image",
            content_type="image/gif",
        )
        form = ProfileUpdateForm(
            data=self.get_valid_form_data(),
            files={"image": uploaded_file},
            instance=self.user.profile,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)
