import logging
from collections.abc import Callable

import sentry_sdk
from django.conf import settings
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from .models import BorrowdUser, UserActivityDay

logger = logging.getLogger("borrowd.users.activity")

SESSION_KEY = "activity_recorded_on"

# The Django admin isn't product activity; skip it so moderation work
# doesn't count toward engagement metrics. Static and media paths are
# skipped for the same reason: they're asset fetches, not product activity.
_ADMIN_PATH_PREFIX = "/admin/"


def _is_excluded_path(path: str) -> bool:
    static_prefix = "/" + settings.STATIC_URL.lstrip("/")
    # An empty prefix (e.g. an unset MEDIA_URL) would match every path via
    # startswith(""), silently disabling tracking entirely, so only ever
    # match on a non-empty prefix.
    excluded = (
        prefix
        for prefix in (_ADMIN_PATH_PREFIX, static_prefix, settings.MEDIA_URL)
        if prefix
    )
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
        # Anonymous requests, including unauthenticated health checks, never
        # narrow to BorrowdUser here, so they're excluded without a
        # dedicated path check.
        user = request.user
        if isinstance(user, BorrowdUser) and not _is_excluded_path(request.path):
            self._record_if_needed(request, user)
        return self.get_response(request)

    @staticmethod
    def _record_if_needed(request: HttpRequest, user: BorrowdUser) -> None:
        today = timezone.now().date()
        if request.session.get(SESSION_KEY) == today.isoformat():
            return
        try:
            UserActivityDay.objects.get_or_create(user=user, date=today)
        except DatabaseError:
            # A metrics write must never break the user's request. Don't set
            # the session key, so the next request retries.
            logger.exception("Failed to record user activity for user %s", user.pk)
            sentry_sdk.capture_exception()
            return
        request.session[SESSION_KEY] = today.isoformat()
