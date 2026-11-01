import json
from copy import deepcopy
from functools import lru_cache
from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.utils.cache import patch_cache_control

from borrowd_web.pwa import (
    PWA_DARK_COLOR,
    PWA_ICON_VERSION,
    PWA_LIGHT_COLOR,
)


@lru_cache
def _read_manifest_template() -> dict[str, Any]:
    manifest_path = settings.BASE_DIR / "static" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise TypeError("The PWA manifest must contain a JSON object.")
    return {key: value for key, value in manifest.items() if isinstance(key, str)}


def favicon(request: HttpRequest) -> FileResponse:
    file = (settings.BASE_DIR / "static" / "favicon.ico").open("rb")
    return FileResponse(file, content_type="image/x-icon")


def web_app_manifest(request: HttpRequest) -> HttpResponse:
    manifest = deepcopy(_read_manifest_template())
    color_scheme = request.GET.get("color_scheme", "")
    if color_scheme not in {"dark", "light"}:
        color_scheme = "light"

    dark_suffix = "-dark" if color_scheme == "dark" else ""
    color = PWA_DARK_COLOR if color_scheme == "dark" else PWA_LIGHT_COLOR
    manifest["theme_color"] = color
    manifest["background_color"] = color
    for icon in manifest["icons"]:
        original_src = icon["src"]
        if original_src.endswith(".svg"):
            icon_path = "icon.svg"
            icon_query = f"?color_scheme={color_scheme}"
        elif icon["purpose"] == "maskable":
            size = icon["sizes"].split("x")[0]
            icon_path = f"icon-maskable{dark_suffix}-{size}.png"
            icon_query = ""
        else:
            size = icon["sizes"].split("x")[0]
            icon_path = f"icon{dark_suffix}-{size}.png"
            icon_query = ""
        icon_url = static(icon_path)
        version_separator = "&" if icon_query else "?"
        icon["src"] = f"{icon_url}{icon_query}{version_separator}v={PWA_ICON_VERSION}"

    response = HttpResponse(
        json.dumps(manifest), content_type="application/manifest+json"
    )
    patch_cache_control(response, public=True, max_age=3600)
    return response


def index(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("item-list")
    return redirect("account_login")


@login_required
def faq(request: HttpRequest) -> HttpResponse:
    return render(request, "web/faq.html")


@login_required
def onboarding_step1(request: HttpRequest) -> HttpResponse:
    return render(request, "onboarding/step1.html")


@login_required
def onboarding_step2(request: HttpRequest) -> HttpResponse:
    return render(request, "onboarding/step2.html")


@login_required
def onboarding_step3(request: HttpRequest) -> HttpResponse:
    return render(request, "onboarding/step3.html")


# View to handle "complete onboarding"
@login_required
def onboarding_complete(request: HttpRequest) -> HttpResponse:
    # Get next in session and remove it from session
    next_url = request.session.pop("post_onboarding_redirect", None)
    if next_url:
        return redirect(next_url)

    return redirect("item-list")
