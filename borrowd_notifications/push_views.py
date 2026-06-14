import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from .models import PushSubscription


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
    except (json.JSONDecodeError, KeyError, TypeError):
        return HttpResponse(status=400)

    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"user": request.user, "p256dh": p256dh, "auth": auth},
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

    PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return HttpResponse(status=204)
