from django import forms

from .models import Item


class ItemForm(forms.ModelForm[Item]):
    """Base form for Item operations with consistent styling."""

    class Meta:
        model = Item
        fields = ["name", "description", "categories", "trust_level_required"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "input input-bordered w-full", "placeholder": "Enter item name..."}
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "textarea textarea-bordered w-full resize-y",
                    "placeholder": "Enter a detailed description of your item...",
                }
            ),
            "categories": forms.SelectMultiple(attrs={"class": "select select-bordered w-full"}),
            "trust_level_required": forms.Select(attrs={"class": "select select-bordered w-full"}),
        }


class ItemCreateWithPhotoForm(ItemForm):
    """Form for creating Items with optional photo upload."""

    image = forms.ImageField(
        required=False,
        label="Photo (optional)",
        widget=forms.FileInput(
            attrs={"class": "file-input file-input-bordered w-full max-w-full", "accept": "image/*"}
        ),
    )
