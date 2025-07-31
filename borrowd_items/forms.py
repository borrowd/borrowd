from django import forms

from .models import Item


class ItemCreateWithPhotoForm(forms.ModelForm[Item]):
    image = forms.ImageField(required=False, label="Photo (optional)")

    class Meta:
        model = Item
        fields = ["name", "description", "category", "trust_level_required"]
