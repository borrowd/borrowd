from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.template.defaultfilters import filesizeformat

MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp"]
ALLOWED_IMAGE_ACCEPT = ",".join(f".{ext}" for ext in ALLOWED_IMAGE_EXTENSIONS)


def validate_image_size(image: UploadedFile) -> None:
    """Validate that an uploaded image doesn't exceed the maximum file size."""
    if image.size and image.size > MAX_PHOTO_SIZE_BYTES:
        raise forms.ValidationError(
            f"File size must be under {filesizeformat(MAX_PHOTO_SIZE_BYTES)}. "
            f"Your file is {filesizeformat(image.size)}."
        )
