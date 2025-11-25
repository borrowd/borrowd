from typing import Any

from django.conf import settings
from django.http import HttpRequest

from borrowd_beta.forms import BetaSignupForm


def beta_status(request: HttpRequest) -> dict[str, Any]:
    has_beta_access = (
        getattr(request, "has_beta_access", False)
        if settings.BORROWD_BETA_ENABLED
        else True
    )
    return {
        "borrowd_beta_enabled": settings.BORROWD_BETA_ENABLED,
        "has_beta_access": has_beta_access,
        "beta_signup_form": None if has_beta_access else BetaSignupForm(),
    }
