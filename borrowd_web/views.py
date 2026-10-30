from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render

# Paths that stay in the browser even when the native app is installed.
_UNIVERSAL_LINK_EXCLUDED_PATHS = ("/admin/*", "/static/*", "/media/*", "/.well-known/*")


def favicon(request: HttpRequest) -> FileResponse:
    file = (settings.BASE_DIR / "static" / "favicon.ico").open("rb")
    return FileResponse(file, content_type="image/x-icon")


def apple_app_site_association(request: HttpRequest) -> JsonResponse:
    """Let iOS open links to this site in the native app (Universal Links)."""
    if not settings.APPLE_TEAM_ID:
        raise Http404("APPLE_TEAM_ID is not configured.")
    components: list[dict[str, str | bool]] = [
        {"/": path, "exclude": True} for path in _UNIVERSAL_LINK_EXCLUDED_PATHS
    ]
    components.append({"/": "/*"})
    return JsonResponse(
        {
            "applinks": {
                "details": [
                    {
                        "appIDs": [
                            f"{settings.APPLE_TEAM_ID}.{settings.NATIVE_APP_ID}"
                        ],
                        "components": components,
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
            }
        ],
        safe=False,
    )


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
