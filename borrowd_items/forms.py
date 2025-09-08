from django import forms

from .models import Item


class ItemForm(forms.ModelForm[Item]):
    """Base form for Item operations with consistent styling."""

    class Meta:
        model = Item
        fields = ["name", "description", "category", "trust_level_required"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "w-full", "placeholder": "Enter item name..."}
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "w-full resize-y",
                    "placeholder": "Enter a detailed description of your item...",
                }
            ),
            "category": forms.Select(attrs={"class": "w-full"}),
            "trust_level_required": forms.Select(attrs={"class": "w-full"}),
        }


class ItemCreateWithPhotoForm(ItemForm):
    """Form for creating Items with optional photo upload."""

    image = forms.ImageField(
        required=False,
        label="Photo (optional)",
        widget=forms.FileInput(
            attrs={"class": "w-full max-w-full", "accept": "image/*"}
        ),
    )
