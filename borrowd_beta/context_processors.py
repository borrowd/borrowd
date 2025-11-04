from typing import Any

from django.conf import settings
from django.http import HttpRequest

from borrowd_beta.forms import BetaSignupForm


def beta_status(request: HttpRequest) -> dict[str, Any]:
    if settings.BORROWD_BETA_ENABLED:
        has_beta_access = getattr(request, "has_beta_access", False)
        return {
            "has_beta_access": has_beta_access,
            "beta_signup_form": None if has_beta_access else BetaSignupForm(),
        }
    else:
        return {"has_beta_access": True, "beta_signup_form": None}
