import json
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from borrowd_users.request import get_authenticated_user

from .models import PushSubscription

# Real browsers only ever issue Web Push endpoints from this small set of
# vendor push services. Rejecting anything else stops the server from being
# tricked into POSTing to attacker-chosen URLs (SSRF) via webpush() in
# channels.py.
_ALLOWED_PUSH_ENDPOINT_HOSTS = frozenset(
    {
        "fcm.googleapis.com",
        "updates.push.services.mozilla.com",
        "web.push.apple.com",
    }
)
_ALLOWED_PUSH_ENDPOINT_HOST_SUFFIXES = (".notify.windows.com",)


def _is_allowed_push_endpoint(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return host in _ALLOWED_PUSH_ENDPOINT_HOSTS or host.endswith(
        _ALLOWED_PUSH_ENDPOINT_HOST_SUFFIXES
    )


def service_worker(request: HttpRequest) -> HttpResponse:
    """Serve sw.js from the root path so its scope covers the whole origin."""
    sw_path = settings.BASE_DIR / "static" / "js" / "sw.js"
    js = sw_path.read_text()
    return HttpResponse(js, content_type="application/javascript")


def vapid_public_key(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"publicKey": settings.VAPID_PUBLIC_KEY})


@login_required
@require_POST
def subscribe_push(request: HttpRequest) -> HttpResponse:
    try:
        data = json.loads(request.body)
        endpoint: str = data["endpoint"]
        p256dh: str = data["keys"]["p256dh"]
        auth: str = data["keys"]["auth"]
        if (
            not isinstance(endpoint, str)
            or not isinstance(p256dh, str)
            or not isinstance(auth, str)
        ):
            raise TypeError
    except (json.JSONDecodeError, KeyError, TypeError):
        return HttpResponse(status=400)

    if not _is_allowed_push_endpoint(endpoint):
        return HttpResponse(status=400)

    user = get_authenticated_user(request)
    PushSubscription.objects.update_or_create(
        user=user,
        endpoint=endpoint,
        defaults={"p256dh": p256dh, "auth": auth},
    )
    return HttpResponse(status=201)


@login_required
@require_POST
def unsubscribe_push(request: HttpRequest) -> HttpResponse:
    try:
        data = json.loads(request.body)
        endpoint: str = data["endpoint"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return HttpResponse(status=400)

    user = get_authenticated_user(request)
    PushSubscription.objects.filter(user=user, endpoint=endpoint).delete()
    return HttpResponse(status=204)
