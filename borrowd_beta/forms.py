from django import forms
from django.core.validators import RegexValidator

from borrowd_beta.models import BetaCode


class BetaSignupForm(forms.Form):
    code = forms.CharField(
        min_length=7,
        max_length=7,
        required=True,
        validators=[
            RegexValidator(
                r"^[A-Z0-9]{7}$", "Code must be 7 uppercase letters/numbers."
            )
        ],
    )

    def clean_code(self) -> BetaCode:
        code_str = self.cleaned_data["code"]
        try:
            beta_code = BetaCode.objects.get(code=code_str)
        except BetaCode.DoesNotExist:
            raise forms.ValidationError("Invalid beta code.")
        if beta_code.signups.count() >= beta_code.num_uses:  # type: ignore[attr-defined]
            raise forms.ValidationError("Beta code usage limit reached.")
        return beta_code
