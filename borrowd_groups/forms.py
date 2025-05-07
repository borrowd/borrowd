from django import forms

from borrowd.models import TrustLevel


class GroupJoinForm(forms.Form):
    trust_level = forms.ChoiceField(
        choices=TrustLevel.choices,
        required=True,
        label="Your Trust Level with this Group",
    )
