from typing import Any

from django import forms

from .models import CommunityRequest, CommunityRequestStatus


class CommunityRequestForm(forms.ModelForm[CommunityRequest]):
    """Form for creating lightweight community requests."""

    class Meta:
        model = CommunityRequest
        fields = ["item_name", "description", "category"]
        labels = {
            "item_name": "Item name",
            "description": "Description",
        }
        widgets = {
            "item_name": forms.TextInput(
                attrs={
                    "class": "input w-full text-base bg-primary-content",
                    "placeholder": "Drill, stepladder, etc.",
                    "maxlength": "50",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "textarea w-full text-base resize-y bg-primary-content",
                    "placeholder": "Enter a detailed description of your requested item",
                    "maxlength": "500",
                }
            ),
            "category": forms.Select(
                attrs={"class": "select w-full text-base bg-primary-content"}
            ),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # django-stubs types self.fields values as the base Field, which has
        # no empty_label; category is actually a ModelChoiceField at runtime.
        self.fields["category"].empty_label = "Select a category"  # type: ignore[attr-defined]

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}

        requester = self.instance.requester
        item_name = cleaned_data.get("item_name")
        category = cleaned_data.get("category")

        if requester and item_name and category:
            existing_request = CommunityRequest.objects.filter(
                requester=requester,
                item_name=item_name,
                category=category,
                status=CommunityRequestStatus.OPEN,
            )

            if self.instance.pk:
                existing_request = existing_request.exclude(pk=self.instance.pk)

            if existing_request.exists():
                raise forms.ValidationError(
                    "You already have an open request for this item in that category."
                )

        return cleaned_data
