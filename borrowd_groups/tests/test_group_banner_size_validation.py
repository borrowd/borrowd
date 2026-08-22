from io import BytesIO
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from borrowd.validators import MAX_PHOTO_SIZE_BYTES
from borrowd_groups.forms import GroupCreateForm
from borrowd_users.models import BorrowdUser


def create_test_image(size_bytes: int, format: str = "JPEG") -> BytesIO:
    """Create a test image in memory, padded to approximately size_bytes."""
    image = Image.new("RGB", (100, 100), color="blue")
    buffer = BytesIO()
    image.save(buffer, format=format)
    current_size = buffer.tell()
    if size_bytes > current_size:
        buffer.write(b"\x00" * (size_bytes - current_size))
    buffer.seek(0)
    return buffer


class GroupBannerSizeValidationTests(TestCase):
    owner: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.owner = BorrowdUser.objects.create(
            username="groupowner", email="groupowner@example.com"
        )

    def get_valid_form_data(self) -> dict[str, Any]:
        return {
            "name": "Test Group",
            "description": "A test group",
        }

    def test_form_valid_without_banner(self) -> None:
        form = GroupCreateForm(data=self.get_valid_form_data(), user=self.owner)
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_valid_with_banner_at_size_limit(self) -> None:
        image_data = create_test_image(MAX_PHOTO_SIZE_BYTES)
        uploaded_file = SimpleUploadedFile(
            name="banner.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )
        form = GroupCreateForm(
            data=self.get_valid_form_data(),
            files={"banner": uploaded_file},
            user=self.owner,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_invalid_with_oversized_banner(self) -> None:
        image_data = create_test_image(MAX_PHOTO_SIZE_BYTES + 1)
        uploaded_file = SimpleUploadedFile(
            name="banner.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )
        form = GroupCreateForm(
            data=self.get_valid_form_data(),
            files={"banner": uploaded_file},
            user=self.owner,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("banner", form.errors)

    def test_form_invalid_with_disallowed_extension(self) -> None:
        uploaded_file = SimpleUploadedFile(
            name="banner.gif",
            content=b"not a real image",
            content_type="image/gif",
        )
        form = GroupCreateForm(
            data=self.get_valid_form_data(),
            files={"banner": uploaded_file},
            user=self.owner,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("banner", form.errors)
