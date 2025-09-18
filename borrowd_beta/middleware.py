import re
from typing import Any

from django.conf import settings
from django.shortcuts import redirect

from borrowd_beta.models import BetaSignup


class BetaAccessMiddleware:
    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> Any:
        # Set request variable for context processor
        request.has_beta_access = self.get_beta_signup(request) is not None

        if not request.has_beta_access and self.is_redirect_required(request):
            return redirect(self.signup_redirect_path)

        response = self.get_response(request)
        return response

    @property
    def signup_redirect_path(self) -> str:
        return getattr(settings, "BETA_SIGNUP_REDIRECT_PATH", "/")

    def is_redirect_required(self, request: Any) -> bool:
        is_signup_view = request.path == self.signup_redirect_path
        if is_signup_view:
            return False

        exclude_paths = getattr(settings, "BETA_CHECK_EXCLUDE_PATHS", [])
        for path in exclude_paths:
            if re.match(path, request.path):
                return False

        return True

    @staticmethod
    def get_beta_signup(request: Any) -> BetaSignup | None:
        beta_key = request.COOKIES.get("beta_key")
        if beta_key is None:
            beta_key = request.headers.get("beta_key")

        if beta_key is None:
            return None

        try:
            return BetaSignup.objects.get(token=beta_key)
        except Exception:
            return None
