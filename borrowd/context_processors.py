from django.conf import settings
from django.http import HttpRequest


def use_local_bundling(request: HttpRequest) -> dict[str, str]:
    return {"use_local_bundling": settings.BORROWD_USE_LOCAL_BUNDLING}
