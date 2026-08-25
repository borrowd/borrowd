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

# Backstop threshold for Pillow's own decompression-bomb check, applied
# globally in borrowd/config/base.py. Deliberately looser than
# MAX_IMAGE_PIXELS so it never preempts validate_image_dimensions's own
# comparison below -- that check must stay self-contained and keep working
# even if the global setting is ever changed or removed. This backstop exists
# only to protect decode paths that skip validate_image_dimensions entirely
# (e.g. Django admin).
PILLOW_HARD_LIMIT_MEGAPIXELS = MAX_IMAGE_MEGAPIXELS * 4
PILLOW_HARD_LIMIT_PIXELS = PILLOW_HARD_LIMIT_MEGAPIXELS * 1_000_000


def validate_image_size(image: UploadedFile) -> None:
    """Validate that an uploaded image doesn't exceed the maximum file size."""
    if image.size and image.size > MAX_PHOTO_SIZE_BYTES:
        raise forms.ValidationError(
            f"File size must be under {filesizeformat(MAX_PHOTO_SIZE_BYTES)}. "
            f"Your file is {filesizeformat(image.size)}."
        )


def validate_image_dimensions(image: UploadedFile) -> None:
    """Validate that an uploaded image's pixel count won't blow up decode/resize memory.

    Opening an image only reads its header (cheap) -- this must run before
    anything decodes the full pixel buffer. Enforces MAX_IMAGE_PIXELS via an
    explicit comparison rather than relying on Pillow's own decompression-bomb
    check (which is configured separately, at a looser threshold, purely as a
    backstop for paths that skip this validator entirely -- see
    borrowd/config/base.py); that check is also caught here and translated
    into the same clean error, in case an image is large enough to trip it
    before this function's own comparison is reached.

    Assumes `image` has already been verified as a well-formed image (true
    for every current caller, all of which run this only after Django's own
    forms.ImageField validation has already confirmed the file opens
    correctly) -- a genuinely corrupt/unidentifiable file will raise a raw
    Pillow exception here instead of a clean ValidationError.
    """
    image.seek(0)
    try:
        with Image.open(image) as opened:
            width, height = opened.size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise forms.ValidationError(
            f"Image dimensions are too large. Max is {MAX_IMAGE_MEGAPIXELS} megapixels."
        ) from exc
    finally:
        image.seek(0)

    if width * height > MAX_IMAGE_PIXELS:
        raise forms.ValidationError(
            f"Image dimensions are too large ({width}x{height}px). "
            f"Max is {MAX_IMAGE_MEGAPIXELS} megapixels."
        )
