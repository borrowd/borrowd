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
    color_scheme = request.GET.get("color_scheme", "")
    if color_scheme not in {"dark", "light"}:
        color_scheme = (
            request.headers.get("Sec-CH-Prefers-Color-Scheme", "")
            .strip()
            .strip('"')
            .lower()
        )
    base_icons = [icon for icon in manifest["icons"] if icon["purpose"] == "any"]
    manifest["icons"] = []
    if color_scheme == "dark":
        manifest["background_color"] = "#0b0907"
    else:
        manifest["background_color"] = "#ffffff"
    for icon in base_icons:
        icon_size = icon["sizes"].split("x")[0]
        dark_suffix = "-dark" if color_scheme == "dark" else ""
        maskable_path = (
            settings.BASE_DIR / "static" / f"icon-maskable{dark_suffix}-{icon_size}.png"
        )
        manifest["icons"].append(
            {
                **icon,
                "purpose": "maskable",
                "src": f"/static/{maskable_path.name}?v=4",
            }
        )

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
