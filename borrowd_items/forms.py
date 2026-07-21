from typing import Any

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import FileExtensionValidator
from django.template.defaultfilters import filesizeformat

from borrowd_users.models import BorrowdUser

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

    def __init__(
        self, *args: Any, user: BorrowdUser | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.initial.setdefault("share_with_all_groups", True)
        if user is not None:
            from borrowd_groups.models import MembershipStatus

            self.fields["shared_with_groups"].queryset = user.borrowd_groups.filter(  # type: ignore[attr-defined]
                membership__user=user,
                membership__status=MembershipStatus.ACTIVE,
            )

    class Meta:
        model = Item
        fields = [
            "name",
            "description",
            "categories",
            "share_with_all_groups",
            "shared_with_groups",
        ]
        labels = {
            "name": "Item name",
        }

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "input input-bordered w-full bg-primary-content",
                    "placeholder": "Drill, stepladder, etc...",
                    "maxlength": "40",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "textarea textarea-bordered w-full resize-y bg-primary-content",
                    "placeholder": "Enter a detailed description of your item...",
                    "maxlength": "250",
                }
            ),
            "share_with_all_groups": forms.CheckboxInput(
                attrs={"class": "checkbox checkbox-primary"}
            ),
        }


class ItemCreateWithPhotoForm(ItemForm):
    """Form for creating Items with optional photo upload.

    Also exposes the listing type (lend vs give away)
    """

    class Meta(ItemForm.Meta):
        fields = ItemForm.Meta.fields + ["listing_type"]

    image = forms.ImageField(
        required=False,
        label="Photo (optional)",
        validators=[
            FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS)
        ],
        widget=forms.FileInput(
            attrs={
                "class": "file-input file-input-bordered w-full max-w-full bg-primary-content",
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
