from typing import Any

from django.conf import settings
from django.http import Http404, HttpRequest
from django.http.response import HttpResponseBase
from django.views import View


class MessagingEnabledMixin(View):
    """
    404s every messaging view while MESSAGING_ENABLED is off
    """

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        if not settings.MESSAGING_ENABLED:
            raise Http404
        return super().dispatch(request, *args, **kwargs)
