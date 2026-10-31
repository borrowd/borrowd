import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.cache import patch_vary_headers


def favicon(request: HttpRequest) -> FileResponse:
    file = (settings.BASE_DIR / "static" / "favicon.ico").open("rb")
    return FileResponse(file, content_type="image/x-icon")


def web_app_manifest(request: HttpRequest) -> HttpResponse:
    manifest_path = settings.BASE_DIR / "static" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    color_scheme = (
        request.headers.get("Sec-CH-Prefers-Color-Scheme", "")
        .strip()
        .strip('"')
        .lower()
    )
    if color_scheme == "dark":
        manifest["background_color"] = "#0b0907"
    else:
        manifest["background_color"] = "#ffffff"
        manifest["icons"] = [
            icon for icon in manifest["icons"] if icon["purpose"] == "any"
        ]
    for icon in manifest["icons"]:
        icon_path = settings.BASE_DIR / "static" / icon["src"]
        if color_scheme == "dark":
            filename, separator, size = icon_path.stem.rpartition("-")
            if separator and size.isdigit():
                dark_icon_path = icon_path.with_name(
                    f"{filename}-dark-{size}{icon_path.suffix}"
                )
                if dark_icon_path.is_file():
                    icon_path = dark_icon_path
        icon["src"] = f"/static/{icon_path.name}"

    response = HttpResponse(
        json.dumps(manifest), content_type="application/manifest+json"
    )
    patch_vary_headers(response, ["Sec-CH-Prefers-Color-Scheme"])
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
