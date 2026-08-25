from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.template.defaultfilters import filesizeformat
from PIL import Image

MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp"]
ALLOWED_IMAGE_ACCEPT = ",".join(f".{ext}" for ext in ALLOWED_IMAGE_EXTENSIONS)

# Bounds the raw pixel buffer Pillow decodes before resizing. Compressed file
# size (MAX_PHOTO_SIZE_BYTES) doesn't bound this: a small, well-compressed
# image can still decode to a huge bitmap. This number is sized against our
# smallest deployment's actual container memory, not against typical camera
# resolution -- see docs/image-upload-memory-safety.md.
MAX_IMAGE_MEGAPIXELS = 8
MAX_IMAGE_PIXELS = MAX_IMAGE_MEGAPIXELS * 1_000_000


def validate_image_size(image: UploadedFile) -> None:
    """Validate that an uploaded image doesn't exceed the maximum file size."""
    if image.size and image.size > MAX_PHOTO_SIZE_BYTES:
        raise forms.ValidationError(
            f"File size must be under {filesizeformat(MAX_PHOTO_SIZE_BYTES)}. "
            f"Your file is {filesizeformat(image.size)}."
        )


def validate_image_dimensions(image: UploadedFile) -> None:
    """Validate that an uploaded image's pixel count won't blow up decode/resize memory.

    Opening an image only reads its header (cheap) -- Pillow's own
    decompression-bomb check runs at that point, before anything decodes the
    full pixel buffer. That check is hardened in borrowd/config/base.py to
    match MAX_IMAGE_PIXELS; this just translates it into a clean, user-facing
    error instead of letting a raw Pillow exception escape the form.
    """
    image.seek(0)
    try:
        with Image.open(image):
            pass
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise forms.ValidationError(
            f"Image dimensions are too large. Max is {MAX_IMAGE_MEGAPIXELS} megapixels."
        ) from exc
    finally:
        image.seek(0)
