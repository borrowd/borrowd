from io import BytesIO
from typing import Any

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from borrowd.validators import MAX_IMAGE_PIXELS, MAX_PHOTO_SIZE_BYTES
from borrowd_groups.forms import GroupCreateForm
from borrowd_groups.models import BorrowdGroup
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


def create_oversized_dimension_image() -> BytesIO:
    """A solid-color PNG that's tiny in bytes but decodes to far more pixels
    than MAX_IMAGE_PIXELS -- the byte-size check alone would let this through."""
    width = 10000
    height = (MAX_IMAGE_PIXELS * 3) // width
    image = Image.new("RGB", (width, height), color="blue")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
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

    def test_form_invalid_with_oversized_dimensions(self) -> None:
        image_data = create_oversized_dimension_image()
        content = image_data.read()
        self.assertLess(len(content), MAX_PHOTO_SIZE_BYTES)

        uploaded_file = SimpleUploadedFile(
            name="banner.png",
            content=content,
            content_type="image/png",
        )
        form = GroupCreateForm(
            data=self.get_valid_form_data(),
            files={"banner": uploaded_file},
            user=self.owner,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("banner", form.errors)


class GroupImageModelFieldValidatorTests(TestCase):
    """`logo` has no form/view exposing it -- the only way to set it today is
    Django admin's auto-generated form (or a shell/fixture), which bypasses
    BorrowdGroupForm entirely. These validators live on the model fields
    themselves so admin uploads of `banner` and `logo` are still checked."""

    owner: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.owner = BorrowdUser.objects.create(
            username="modelfieldowner", email="modelfieldowner@example.com"
        )

    def test_valid_logo_passes_full_clean(self) -> None:
        """Baseline: full_clean() succeeds for a valid logo once the
        always-blank perms_group field (only populated by
        BorrowdGroupManager.create_group(), not exercised here) is excluded.
        Without this baseline, the "rejected" tests below could pass for the
        wrong reason -- full_clean() raises for *any* instance built this way,
        regardless of the image field, because perms_group is required."""
        image = Image.new("RGB", (100, 100), color="blue")
        buffer = BytesIO()
        image.save(buffer, format="JPEG")
        buffer.seek(0)
        uploaded_file = SimpleUploadedFile(
            name="logo.jpg",
            content=buffer.read(),
            content_type="image/jpeg",
        )
        group = BorrowdGroup(
            name="Model Field Test Group",
            logo=uploaded_file,
            created_by=self.owner,
            updated_by=self.owner,
        )

        group.full_clean(exclude=["perms_group"])  # should not raise

    def test_oversized_logo_rejected_by_full_clean(self) -> None:
        image_data = create_test_image(MAX_PHOTO_SIZE_BYTES + 1)
        uploaded_file = SimpleUploadedFile(
            name="logo.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )
        group = BorrowdGroup(
            name="Model Field Test Group",
            logo=uploaded_file,
            created_by=self.owner,
            updated_by=self.owner,
        )

        with self.assertRaises(ValidationError) as ctx:
            group.full_clean(exclude=["perms_group"])
        self.assertIn("logo", ctx.exception.message_dict)

    def test_disallowed_extension_logo_rejected_by_full_clean(self) -> None:
        # A real, Pillow-valid image (not just garbage bytes) with a
        # disallowed extension -- this is the scenario the model-field
        # FileExtensionValidator actually protects against in Django admin:
        # admin's auto ModelForm validates image *content* via
        # forms.ImageField before this model-level check ever runs, so
        # garbage bytes would already be rejected for an unrelated reason.
        image = Image.new("RGB", (100, 100), color="blue")
        buffer = BytesIO()
        image.save(buffer, format="GIF")
        buffer.seek(0)
        uploaded_file = SimpleUploadedFile(
            name="logo.gif",
            content=buffer.read(),
            content_type="image/gif",
        )
        group = BorrowdGroup(
            name="Model Field Test Group",
            logo=uploaded_file,
            created_by=self.owner,
            updated_by=self.owner,
        )

        with self.assertRaises(ValidationError) as ctx:
            group.full_clean(exclude=["perms_group"])
        self.assertIn("logo", ctx.exception.message_dict)

    def test_oversized_banner_rejected_by_full_clean(self) -> None:
        image_data = create_test_image(MAX_PHOTO_SIZE_BYTES + 1)
        uploaded_file = SimpleUploadedFile(
            name="banner.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )
        group = BorrowdGroup(
            name="Model Field Test Group",
            banner=uploaded_file,
            created_by=self.owner,
            updated_by=self.owner,
        )

        with self.assertRaises(ValidationError) as ctx:
            group.full_clean(exclude=["perms_group"])
        self.assertIn("banner", ctx.exception.message_dict)
