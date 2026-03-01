from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import FileExtensionValidator
from django.template.defaultfilters import filesizeformat

from .models import Item, ItemPhoto

MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
ALLOWED_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp"]
ALLOWED_IMAGE_ACCEPT = ",".join(f".{ext}" for ext in ALLOWED_IMAGE_EXTENSIONS)


def validate_image_size(image: UploadedFile) -> None:
    """Validate that uploaded image doesn't exceed maximum file size."""
    if image.size and image.size > MAX_PHOTO_SIZE_BYTES:
        raise forms.ValidationError(
            f"File size must be under {filesizeformat(MAX_PHOTO_SIZE_BYTES)}. "
            f"Your file is {filesizeformat(image.size)}."
        )


class ItemForm(forms.ModelForm[Item]):
    """Base form for Item operations with consistent styling."""

    class Meta:
        model = Item
        fields = ["name", "description", "categories", "trust_level_required"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "placeholder": "Drill, stepladder, etc...",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "textarea textarea-bordered w-full resize-y",
                    "placeholder": "Enter a detailed description of your item...",
                }
            ),
            "trust_level_required": forms.Select(
                attrs={"class": "select select-bordered w-full"}
            ),
        }


class ItemCreateWithPhotoForm(ItemForm):
    """Form for creating Items with optional photo upload."""

    image = forms.ImageField(
        required=False,
        label="Photo (optional)",
        validators=[
            FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS)
        ],
        widget=forms.FileInput(
            attrs={
                "class": "file-input file-input-bordered w-full max-w-full",
                "accept": ALLOWED_IMAGE_ACCEPT,
            }
        ),
    )

    def clean_image(self) -> UploadedFile | None:
        image: UploadedFile | None = self.cleaned_data.get("image")
        if image:
            validate_image_size(image)
        return image


class ItemPhotoForm(forms.ModelForm[ItemPhoto]):
    """Form for uploading photos to an existing Item."""

    image = forms.ImageField(
        required=True,
        validators=[
            FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS)
        ],
        widget=forms.FileInput(
            attrs={
                "class": "file-input file-input-bordered w-full max-w-full",
                "accept": ALLOWED_IMAGE_ACCEPT,
            }
        ),
    )

    class Meta:
        model = ItemPhoto
        fields = ["image"]

    def clean_image(self) -> UploadedFile | None:
        image: UploadedFile | None = self.cleaned_data.get("image")
        if image:
            validate_image_size(image)
        return image
