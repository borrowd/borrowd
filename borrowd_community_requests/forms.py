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
            "description": "Item description",
        }
        widgets = {
            "item_name": forms.TextInput(
                attrs={
                    "class": "input input-bordered w-full bg-primary-content",
                    "placeholder": "Drill, stepladder, etc.",
                    "maxlength": "50",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "textarea textarea-bordered w-full resize-y bg-primary-content",
                    "placeholder": "Enter a detailed description of your requested item",
                    "maxlength": "500",
                }
            ),
            "category": forms.Select(
                attrs={"class": "select select-bordered w-full bg-primary-content"}
            ),
        }

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
