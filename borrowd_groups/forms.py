from django import forms

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup


class GroupCreateForm(forms.ModelForm[BorrowdGroup]):
    trust_level = forms.ChoiceField(
        choices=sorted(TrustLevel.choices, reverse=True),
        required=True,
        label="Your Trust Level with this Group",
        initial=TrustLevel.HIGH,
    )

    class Meta:
        model = BorrowdGroup
        fields = [
            "name",
            "description",
            "logo",
            "banner",
            "membership_requires_approval",
            "trust_level",
        ]


class GroupJoinForm(forms.Form):
    trust_level = forms.ChoiceField(
        choices=TrustLevel.choices,
        required=True,
        label="Your Trust Level with this Group",
    )


class UpdateTrustLevelForm(forms.Form):
    trust_level = forms.ChoiceField(
        choices=TrustLevel.choices,
        required=True,
        label="Your Trust Level with this Group",
        help_text="Update your trust level to control what items you share with this group.",
    )
