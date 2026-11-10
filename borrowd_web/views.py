import json
from copy import deepcopy
from functools import lru_cache
from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
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


# Paths that stay in the browser even when the native app is installed.
_APP_LINK_EXCLUDED_PATHS = ("/admin/*", "/static/*", "/media/*", "/.well-known/*")


def _app_link_path_rules(catch_all: str) -> list[dict[str, str | bool]]:
    """Exclude _APP_LINK_EXCLUDED_PATHS and allow everything else.

    Both iOS and Android use the first rule that matches, so the exclusions
    must come before the catch-all.
    """
    rules: list[dict[str, str | bool]] = [
        {"/": path, "exclude": True} for path in _APP_LINK_EXCLUDED_PATHS
    ]
    rules.append({"/": catch_all})
    return rules


def favicon(request: HttpRequest) -> FileResponse:
    file = (settings.BASE_DIR / "static" / "favicon.ico").open("rb")
    return FileResponse(file, content_type="image/x-icon")


def apple_app_site_association(request: HttpRequest) -> JsonResponse:
    """Let iOS open links to this site in the native app (Universal Links)."""
    if not settings.APPLE_TEAM_ID:
        raise Http404("APPLE_TEAM_ID is not configured.")
    return JsonResponse(
        {
            "applinks": {
                "details": [
                    {
                        "appIDs": [
                            f"{settings.APPLE_TEAM_ID}.{settings.NATIVE_APP_ID}"
                        ],
                        "components": _app_link_path_rules("/*"),
                    }
                ]
            }
        }
    )


def assetlinks(request: HttpRequest) -> JsonResponse:
    """Let Android open links to this site in the native app (App Links)."""
    if not settings.ANDROID_CERT_SHA256_FINGERPRINTS:
        raise Http404("ANDROID_CERT_SHA256_FINGERPRINTS is not configured.")
    return JsonResponse(
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": settings.NATIVE_APP_ID,
                    "sha256_cert_fingerprints": (
                        settings.ANDROID_CERT_SHA256_FINGERPRINTS
                    ),
                },
                # Android 15+ only ("Dynamic App Links"); earlier versions
                # ignore this and open every path in the app.
                "relation_extensions": {
                    "delegate_permission/common.handle_all_urls": {
                        "dynamic_app_link_components": _app_link_path_rules("*")
                    }
                },
            }
        ],
        safe=False,
    )


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
