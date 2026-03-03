"""
Tests for photo size validation in item forms.

Covers:
- validate_image_size function
- ItemCreateWithPhotoForm (creating an item) image size validation
- ItemPhotoForm (updating an item) image size validation
- Some basic edge cases (corrupted file, zero byte sizes, etc)
"""

from io import BytesIO
from typing import Any, cast

from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.test import TestCase
from django.utils.datastructures import MultiValueDict
from PIL import Image  # type: ignore[import-not-found]

from borrowd.models import TrustLevel
from borrowd_items.forms import (
    ALLOWED_IMAGE_EXTENSIONS,
    MAX_PHOTO_SIZE_BYTES,
    ItemCreateWithPhotoForm,
    ItemPhotoForm,
    validate_image_size,
)
from borrowd_items.models import Item, ItemCategory
from borrowd_users.models import BorrowdUser


def create_test_image(
    size_bytes: int | None = None,
    width: int = 100,
    height: int = 100,
    format: str = "JPEG",
) -> BytesIO:
    """
    Create a test image in memory.

    If size_bytes is provided, pads the image to approximately that size.
    """
    image = Image.new("RGB", (width, height), color="red")
    buffer = BytesIO()
    image.save(buffer, format=format)

    if size_bytes is not None:
        current_size = buffer.tell()
        if size_bytes > current_size:
            # Pad with null bytes to reach target size
            buffer.write(b"\x00" * (size_bytes - current_size))

    buffer.seek(0)
    return buffer


def make_files(
    uploaded_file: SimpleUploadedFile,
) -> MultiValueDict[str, UploadedFile]:
    """Create a properly typed files dict for form testing."""
    return cast(
        MultiValueDict[str, UploadedFile],
        {"image": uploaded_file},
    )


def make_empty_files() -> MultiValueDict[str, UploadedFile]:
    """Create an empty files dict for form testing."""
    return cast(MultiValueDict[str, UploadedFile], {})


class ValidateImageSizeFunctionTests(TestCase):
    """Tests for the validate_image_size function."""

    def test_valid_size_image_passes(self) -> None:
        """Image under the size limit passes validation."""
        # If max size = 2mb, this is 1mb
        image_data = create_test_image(size_bytes=MAX_PHOTO_SIZE_BYTES // 2)
        uploaded_file = SimpleUploadedFile(
            name="test.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        # Should not raise
        validate_image_size(uploaded_file)

    def test_exact_limit_image_passes(self) -> None:
        """Image exactly at the size limit passes validation."""
        image_data = create_test_image(size_bytes=MAX_PHOTO_SIZE_BYTES)
        uploaded_file = SimpleUploadedFile(
            name="test.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        # Should not raise
        validate_image_size(uploaded_file)

    def test_oversized_image_raises_validation_error(self) -> None:
        """Image exceeding the size limit (by 1 byte) raises ValidationError."""
        from django import forms

        image_data = create_test_image(size_bytes=MAX_PHOTO_SIZE_BYTES + 1)
        uploaded_file = SimpleUploadedFile(
            name="test.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        with self.assertRaises(forms.ValidationError):
            validate_image_size(uploaded_file)

    def test_significantly_oversized_image_raises_validation_error(self) -> None:
        """Large image raises ValidationError"""
        from django import forms

        oversized_bytes = MAX_PHOTO_SIZE_BYTES * 5
        image_data = create_test_image(size_bytes=oversized_bytes)
        uploaded_file = SimpleUploadedFile(
            name="large.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        with self.assertRaises(forms.ValidationError):
            validate_image_size(uploaded_file)


class ItemCreateWithPhotoFormSizeValidationTests(TestCase):
    """Tests for photo size validation in ItemCreateWithPhotoForm."""

    owner: BorrowdUser
    category: ItemCategory

    @classmethod
    def setUpTestData(cls) -> None:
        """Create shared fixtures."""
        cls.owner = BorrowdUser.objects.create(
            username="testowner",
            email="testowner@example.com",
        )
        cls.category = ItemCategory.objects.create(
            name="Test Category",
            description="A test category",
        )

    def get_valid_form_data(self) -> dict[str, Any]:
        """Return valid form data without image."""
        return {
            "name": "Test Item",
            "description": "A test item description",
            "categories": [self.category.pk],
            "trust_level_required": TrustLevel.STANDARD,
        }

    def test_form_valid_without_image(self) -> None:
        """Form validates successfully without an image (image is optional)."""
        form = ItemCreateWithPhotoForm(data=self.get_valid_form_data())

        self.assertTrue(form.is_valid(), form.errors)

    def test_form_valid_with_small_image(self) -> None:
        """Form validates successfully with a small image."""
        # If max size = 2mb, this is 100kb
        image_data = create_test_image(size_bytes=MAX_PHOTO_SIZE_BYTES // 20)
        uploaded_file = SimpleUploadedFile(
            name="small.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        form = ItemCreateWithPhotoForm(
            data=self.get_valid_form_data(),
            files=make_files(uploaded_file),
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_form_valid_with_image_at_size_limit(self) -> None:
        """Form validates successfully with image exactly at the size limit."""
        image_data = create_test_image(size_bytes=MAX_PHOTO_SIZE_BYTES)
        uploaded_file = SimpleUploadedFile(
            name="at_limit.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        form = ItemCreateWithPhotoForm(
            data=self.get_valid_form_data(),
            files=make_files(uploaded_file),
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_form_invalid_with_oversized_image(self) -> None:
        """Form rejects image exceeding the size limit (by 1 byte)."""
        image_data = create_test_image(size_bytes=MAX_PHOTO_SIZE_BYTES + 1)
        uploaded_file = SimpleUploadedFile(
            name="oversized.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        form = ItemCreateWithPhotoForm(
            data=self.get_valid_form_data(),
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_form_invalid_with_large_oversized_image(self) -> None:
        """Form rejects significantly oversized image."""
        oversized_bytes = MAX_PHOTO_SIZE_BYTES * 5
        image_data = create_test_image(size_bytes=oversized_bytes)
        uploaded_file = SimpleUploadedFile(
            name="very_large.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        form = ItemCreateWithPhotoForm(
            data=self.get_valid_form_data(),
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)


class ItemPhotoFormSizeValidationTests(TestCase):
    """Tests for photo size validation in ItemPhotoForm."""

    owner: BorrowdUser
    category: ItemCategory
    item: Item

    @classmethod
    def setUpTestData(cls) -> None:
        """Create shared fixtures."""
        cls.owner = BorrowdUser.objects.create(
            username="photoowner",
            email="photoowner@example.com",
        )
        cls.category = ItemCategory.objects.create(
            name="Photo Test Category",
            description="Category for photo tests",
        )
        cls.item = Item.objects.create(
            name="Item for Photo Tests",
            description="An item to add photos to",
            owner=cls.owner,
            trust_level_required=TrustLevel.STANDARD,
        )
        cls.item.categories.add(cls.category)

    def test_form_valid_with_small_image(self) -> None:
        """Form validates successfully with a small image."""
        # If max size = 2mb, this is 100kb
        image_data = create_test_image(size_bytes=MAX_PHOTO_SIZE_BYTES // 20)
        uploaded_file = SimpleUploadedFile(
            name="small.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        form = ItemPhotoForm(
            data={},
            files=make_files(uploaded_file),
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_form_valid_with_image_at_size_limit(self) -> None:
        """Form validates successfully with image exactly at the size limit."""
        image_data = create_test_image(size_bytes=MAX_PHOTO_SIZE_BYTES)
        uploaded_file = SimpleUploadedFile(
            name="at_limit.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        form = ItemPhotoForm(
            data={},
            files=make_files(uploaded_file),
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_form_invalid_with_oversized_image(self) -> None:
        """Form rejects image exceeding the size limit."""
        image_data = create_test_image(size_bytes=MAX_PHOTO_SIZE_BYTES + 1)
        uploaded_file = SimpleUploadedFile(
            name="oversized.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        form = ItemPhotoForm(
            data={},
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_form_invalid_with_large_oversized_image(self) -> None:
        """Form rejects significantly oversized image."""
        oversized_bytes = MAX_PHOTO_SIZE_BYTES * 3
        image_data = create_test_image(size_bytes=oversized_bytes)
        uploaded_file = SimpleUploadedFile(
            name="large.jpg",
            content=image_data.read(),
            content_type="image/jpeg",
        )

        form = ItemPhotoForm(
            data={},
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_form_requires_image(self) -> None:
        """Form requires an image to be provided."""
        form = ItemPhotoForm(data={}, files=make_empty_files())

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)


class ImageEdgeCaseTests(TestCase):
    """Tests for edge cases: empty files, corrupted images, invalid formats."""

    owner: BorrowdUser
    category: ItemCategory

    @classmethod
    def setUpTestData(cls) -> None:
        """Create shared fixtures."""
        cls.owner = BorrowdUser.objects.create(
            username="edgecaseowner",
            email="edgecaseowner@example.com",
        )
        cls.category = ItemCategory.objects.create(
            name="Edge Case Category",
            description="Category for edge case tests",
        )

    def get_valid_form_data(self) -> dict[str, Any]:
        """Return valid form data without image."""
        return {
            "name": "Test Item",
            "description": "A test item description",
            "categories": [self.category.pk],
            "trust_level_required": TrustLevel.STANDARD,
        }

    # Zero byte / empty file tests

    def test_zero_byte_file_rejected_by_create_form(self) -> None:
        """Empty file (0 bytes) is rejected by ItemCreateWithPhotoForm."""
        uploaded_file = SimpleUploadedFile(
            name="empty.jpg",
            content=b"",
            content_type="image/jpeg",
        )

        form = ItemCreateWithPhotoForm(
            data=self.get_valid_form_data(),
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_zero_byte_file_rejected_by_photo_form(self) -> None:
        """Empty file (0 bytes) is rejected by ItemPhotoForm."""
        uploaded_file = SimpleUploadedFile(
            name="empty.jpg",
            content=b"",
            content_type="image/jpeg",
        )

        form = ItemPhotoForm(
            data={},
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    # Corrupted image tests

    def test_corrupted_image_rejected_by_create_form(self) -> None:
        """File with random bytes (not a valid image) is rejected."""
        corrupted_content = b"\x00\x01\x02\x03\x04\x05random garbage data"
        uploaded_file = SimpleUploadedFile(
            name="corrupted.jpg",
            content=corrupted_content,
            content_type="image/jpeg",
        )

        form = ItemCreateWithPhotoForm(
            data=self.get_valid_form_data(),
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_corrupted_image_rejected_by_photo_form(self) -> None:
        """File with random bytes (not a valid image) is rejected."""
        corrupted_content = b"\x00\x01\x02\x03\x04\x05random garbage data"
        uploaded_file = SimpleUploadedFile(
            name="corrupted.jpg",
            content=corrupted_content,
            content_type="image/jpeg",
        )

        form = ItemPhotoForm(
            data={},
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_truncated_jpeg_rejected_by_create_form(self) -> None:
        """JPEG file with valid header but truncated data is rejected."""
        # Valid JPEG header (SOI marker) but incomplete file
        truncated_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
        uploaded_file = SimpleUploadedFile(
            name="truncated.jpg",
            content=truncated_jpeg,
            content_type="image/jpeg",
        )

        form = ItemCreateWithPhotoForm(
            data=self.get_valid_form_data(),
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_truncated_png_rejected_by_photo_form(self) -> None:
        """PNG file with valid header but truncated data is rejected."""
        # Valid PNG header but incomplete file
        truncated_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00"
        uploaded_file = SimpleUploadedFile(
            name="truncated.png",
            content=truncated_png,
            content_type="image/png",
        )

        form = ItemPhotoForm(
            data={},
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    # Non-image file with image extension tests

    def test_text_file_with_jpg_extension_rejected_by_create_form(self) -> None:
        """Text content with .jpg extension is rejected."""
        text_content = b"This is just plain text, not an image at all."
        uploaded_file = SimpleUploadedFile(
            name="fake_image.jpg",
            content=text_content,
            content_type="image/jpeg",
        )

        form = ItemCreateWithPhotoForm(
            data=self.get_valid_form_data(),
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_text_file_with_png_extension_rejected_by_photo_form(self) -> None:
        """Text content with .png extension is rejected."""
        text_content = b"This is just plain text, not an image at all."
        uploaded_file = SimpleUploadedFile(
            name="fake_image.png",
            content=text_content,
            content_type="image/png",
        )

        form = ItemPhotoForm(
            data={},
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_html_file_with_image_extension_rejected(self) -> None:
        """HTML content disguised as image is rejected."""
        html_content = b"<html><body><script>alert('xss')</script></body></html>"
        uploaded_file = SimpleUploadedFile(
            name="malicious.jpg",
            content=html_content,
            content_type="image/jpeg",
        )

        form = ItemCreateWithPhotoForm(
            data=self.get_valid_form_data(),
            files=make_files(uploaded_file),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    # Very small but valid image test

    def test_minimal_valid_image_accepted(self) -> None:
        """Smallest possible valid image (1x1 pixel) is accepted."""
        image = Image.new("RGB", (1, 1), color="red")
        buffer = BytesIO()
        image.save(buffer, format="JPEG")
        buffer.seek(0)

        uploaded_file = SimpleUploadedFile(
            name="tiny_valid.jpg",
            content=buffer.read(),
            content_type="image/jpeg",
        )

        form = ItemCreateWithPhotoForm(
            data=self.get_valid_form_data(),
            files=make_files(uploaded_file),
        )

        self.assertTrue(form.is_valid(), form.errors)


class ItemPhotoFileExtensionValidationTests(TestCase):
    """Tests for photo file extension validation."""

    def test_allowed_extensions_include_common_formats(self) -> None:
        """Allowed extensions include standard image formats."""
        self.assertIn("jpg", ALLOWED_IMAGE_EXTENSIONS)
        self.assertIn("jpeg", ALLOWED_IMAGE_EXTENSIONS)
        self.assertIn("png", ALLOWED_IMAGE_EXTENSIONS)
        self.assertIn("webp", ALLOWED_IMAGE_EXTENSIONS)
