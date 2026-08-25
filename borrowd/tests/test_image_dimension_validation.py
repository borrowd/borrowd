"""
Tests for pixel-dimension validation and its Pillow-level backstop.

Covers:
- validate_image_dimensions function
- Why a byte-size cap alone can't bound decode memory (decompression-bomb-shaped image)
- The global Pillow hardening in settings, which protects paths that skip our
  form validators entirely (e.g. Django admin)
"""

from io import BytesIO

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from borrowd.validators import (
    MAX_IMAGE_PIXELS,
    MAX_PHOTO_SIZE_BYTES,
    validate_image_dimensions,
)


def create_test_image(
    width: int, height: int, format: str = "PNG", color: str = "blue"
) -> BytesIO:
    """Create a solid-color test image in memory at the given pixel dimensions."""
    image = Image.new("RGB", (width, height), color=color)
    buffer = BytesIO()
    image.save(buffer, format=format)
    buffer.seek(0)
    return buffer


class ValidateImageDimensionsFunctionTests(TestCase):
    """Tests for the validate_image_dimensions function."""

    def test_image_under_pixel_cap_passes(self) -> None:
        image_data = create_test_image(width=100, height=100)
        uploaded_file = SimpleUploadedFile(
            name="small.png", content=image_data.read(), content_type="image/png"
        )

        validate_image_dimensions(uploaded_file)  # should not raise

    def test_image_at_exact_pixel_cap_passes(self) -> None:
        width, height = 2500, 3200  # 8,000,000px == MAX_IMAGE_PIXELS
        self.assertEqual(width * height, MAX_IMAGE_PIXELS)
        image_data = create_test_image(width=width, height=height)
        uploaded_file = SimpleUploadedFile(
            name="at_limit.png", content=image_data.read(), content_type="image/png"
        )

        validate_image_dimensions(uploaded_file)  # should not raise

    def test_image_over_pixel_cap_raises(self) -> None:
        width, height = 2501, 3200  # 8,003,200px > MAX_IMAGE_PIXELS
        image_data = create_test_image(width=width, height=height)
        uploaded_file = SimpleUploadedFile(
            name="over_limit.png", content=image_data.read(), content_type="image/png"
        )

        with self.assertRaises(forms.ValidationError):
            validate_image_dimensions(uploaded_file)

    def test_decompression_bomb_shaped_image_raises_despite_small_file_size(
        self,
    ) -> None:
        """A solid-color image compresses to a tiny file but decodes to a huge
        bitmap -- this is exactly what the byte-size cap can't catch, and what
        this validator exists for."""
        width, height = 10000, 10000  # 100,000,000px
        image_data = create_test_image(width=width, height=height)
        content = image_data.read()

        # Prove the byte-size check alone would have let this through.
        self.assertLess(len(content), MAX_PHOTO_SIZE_BYTES)

        uploaded_file = SimpleUploadedFile(
            name="bomb.png", content=content, content_type="image/png"
        )

        with self.assertRaises(forms.ValidationError):
            validate_image_dimensions(uploaded_file)

    def test_file_pointer_is_reset_after_validation(self) -> None:
        """Downstream code (Django's own field cleaning, ImageKit processing)
        needs to read the file from the start again."""
        image_data = create_test_image(width=100, height=100)
        uploaded_file = SimpleUploadedFile(
            name="small.png", content=image_data.read(), content_type="image/png"
        )

        validate_image_dimensions(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 0)


class PillowDecompressionBombHardeningTests(TestCase):
    """Tests for the global Pillow hardening configured in borrowd/config/base.py.

    These exercise Pillow directly, bypassing validate_image_dimensions
    entirely, to prove the backstop holds for paths that skip our form
    validators (e.g. Django admin).
    """

    def test_pillow_max_image_pixels_matches_our_cap(self) -> None:
        self.assertEqual(Image.MAX_IMAGE_PIXELS, MAX_IMAGE_PIXELS)

    def test_decompression_bomb_warning_is_raised_as_error(self) -> None:
        """Pillow only warns (doesn't raise) between 1x and 2x MAX_IMAGE_PIXELS
        by default; our settings convert that warning into a hard error."""
        pixels_in_warning_zone = int(MAX_IMAGE_PIXELS * 1.5)
        width = 4000
        height = pixels_in_warning_zone // width
        image_data = create_test_image(width=width, height=height)

        with self.assertRaises(Image.DecompressionBombWarning):
            Image.open(image_data)

    def test_decompression_bomb_over_double_cap_raises_error_unconditionally(
        self,
    ) -> None:
        """Above 2x MAX_IMAGE_PIXELS, Pillow raises unconditionally regardless
        of warning filters."""
        pixels_over_double_cap = int(MAX_IMAGE_PIXELS * 2.5)
        width = 4000
        height = pixels_over_double_cap // width
        image_data = create_test_image(width=width, height=height)

        with self.assertRaises(Image.DecompressionBombError):
            Image.open(image_data)
