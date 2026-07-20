from typing import Any, cast

from django import forms

from borrowd_groups.models import BorrowdGroup
from borrowd_users.models import BorrowdUser

DUPLICATE_GROUP_NAME_ERROR = "You already have a group with this name."


class BorrowdGroupForm(forms.ModelForm[BorrowdGroup]):
    user: BorrowdUser | None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.user = cast(BorrowdUser | None, kwargs.pop("user", None))
        super().__init__(*args, **kwargs)

    class Meta:
        model = BorrowdGroup

        fields = [
            "name",
            "description",
            "banner",
            "membership_requires_approval",
        ]

        labels = {
            "name": "Group name",
            "description": "Group description",
            "banner": "Picture (optional)",
            "membership_requires_approval": "",
        }

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "flex justify-center items-center gap-[10px] w-full py-[10.5px] px-3",
                    "placeholder": "100 Broadway Ave Neighbors",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "block w-full h-20 px-3 py-2 box-border",
                    "placeholder": "Enter a helpful description for your group",
                }
            ),
            "banner": forms.ClearableFileInput(
                attrs={
                    "class": (
                        "block w-full text-sm text-gray-600 file:font-semibold "
                        "file:mr-3 file:py-2 file:px-4 "
                        "file:rounded-md file:border-0 "
                        "file:bg-gray-100 file:text-gray-900 "
                        "hover:file:bg-gray-200 "
                    )
                }
            ),
            "membership_requires_approval": forms.CheckboxInput(
                attrs={
                    "class": "h-5 w-5 rounded-md border-gray-300 text-black focus:ring-0",
                }
            ),
        }

    def clean_name(self) -> str:
        name: str | None = self.cleaned_data.get("name")

        if not name:
            raise forms.ValidationError("Group name is required.")

        # Check for duplicate group names owned by the same user
        queryset = BorrowdGroup.objects.filter(
            name=name,
            created_by=self.user,
        )

        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise forms.ValidationError(DUPLICATE_GROUP_NAME_ERROR)

        return name


class GroupCreateForm(BorrowdGroupForm):
    pass


class GroupUpdateForm(BorrowdGroupForm):
    pass
