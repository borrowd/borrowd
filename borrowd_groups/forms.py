from django import forms
from django.forms import formset_factory

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


class GroupInviteEmailForm(forms.Form):
    email = forms.EmailField(
        required=True,
        label="Email",
    )


# using a formset to support multiple email invites, but only showing single email input for now
GroupInviteEmailFormSet = formset_factory(
    GroupInviteEmailForm, extra=0, max_num=10, min_num=1, validate_min=True
)
