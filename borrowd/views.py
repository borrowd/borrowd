# my_app/views.py
import sentry_sdk
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


# we need to enforce app-specific 403 errors here :(
def custom_403_router(
    request: HttpRequest, exception: Exception | None = None
) -> HttpResponse:
    if request.path.startswith("/groups/"):
        template = "groups/403.html"
    else:
        template = "403.html"

    return render(request, template, status=403)


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    sentry_sdk.capture_message(f"CSRF failure: {reason}", level="warning")
    return render(request, "403_csrf.html", status=403)
