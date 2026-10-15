from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from .models import BorrowdUser, UserActivityDay

SESSION_KEY = "activity_recorded_on"

# The Django admin isn't product activity; skip it so moderation work
# doesn't count toward engagement metrics. Static/media paths are skipped
# for the same reason request bodies are small there: no product activity
# to record, just assets. Anonymous requests (including unauthenticated
# health checks) never reach request.user as a BorrowdUser, so they're
# already excluded below without needing a path check.
_EXCLUDED_PATH_PREFIXES = ("/admin/",)


def _is_excluded_path(path: str) -> bool:
    static_prefix = "/" + settings.STATIC_URL.lstrip("/")
    excluded = (*_EXCLUDED_PATH_PREFIXES, static_prefix, settings.MEDIA_URL)
    return any(path.startswith(prefix) for prefix in excluded)


class RecordUserActivityMiddleware:
    """
    Record one UserActivityDay row per authenticated user per UTC calendar
    day. At most one write per user per day: the session value SESSION_KEY
    caches today's date so every other request on the same day is a cheap
    in-memory comparison with no query.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = request.user
        if isinstance(user, BorrowdUser) and not _is_excluded_path(request.path):
            self._record_if_needed(request, user)
        return self.get_response(request)

    @staticmethod
    def _record_if_needed(request: HttpRequest, user: BorrowdUser) -> None:
        today = timezone.now().date()
        if request.session.get(SESSION_KEY) == today.isoformat():
            return
        UserActivityDay.objects.get_or_create(user=user, date=today)
        request.session[SESSION_KEY] = today.isoformat()
