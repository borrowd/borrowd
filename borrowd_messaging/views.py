from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Max, Q, QuerySet
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.generic import DetailView, ListView, View
from django.views.generic.detail import SingleObjectMixin

from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_items.models import TransactionStatus
from borrowd_permissions.mixins import LoginOr404PermissionMixin
from borrowd_permissions.models import ChatThreadOLP
from borrowd_users.request import get_authenticated_user

from .exceptions import InvalidMessageBody, ThreadNotWritable
from .mixins import MessagingEnabledMixin
from .models import MESSAGE_BODY_MAX_LENGTH, ChatThread
from .services import MessagingService

_INVALID_CURSOR_MESSAGE = "`after` must be a message id from this conversation."


class _InvalidCursor(ValueError):
    pass


def _parse_cursor(raw_cursor: str | None, chat_thread: ChatThread) -> int:
    if raw_cursor is None:
        raise _InvalidCursor(_INVALID_CURSOR_MESSAGE)

    try:
        cursor = int(raw_cursor)
    except ValueError as exc:
        raise _InvalidCursor(_INVALID_CURSOR_MESSAGE) from exc

    if cursor < 0 or (
        cursor != 0 and not chat_thread.messages.filter(pk=cursor).exists()
    ):
        raise _InvalidCursor(_INVALID_CURSOR_MESSAGE)
    return cursor


class ChatThreadDetailView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    BorrowdTemplateFinderMixin,
    DetailView[ChatThread],
):
    model = ChatThread
    context_object_name = "chat_thread"
    permission_required = ChatThreadOLP.VIEW

    def get_queryset(self) -> QuerySet[ChatThread]:
        return (
            super()
            .get_queryset()
            .select_related("item", "lender", "borrower", "transaction")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = get_authenticated_user(self.request)
        chat_thread = self.object
        context["other_party"] = (
            chat_thread.borrower
            if user.pk == chat_thread.lender_id
            else chat_thread.lender
        )
        # "messages" collides with django.contrib.messages context processor (for toast). Hence, "chat_messages"
        # See: https://docs.djangoproject.com/en/5.2/ref/contrib/messages/
        # sender__profile: every bubble reads the sender's avatar and full name.
        context["chat_messages"] = chat_thread.messages.select_related(
            "sender__profile"
        ).order_by("id")
        context["message_body_max_length"] = MESSAGE_BODY_MAX_LENGTH
        transaction = chat_thread.transaction
        # to show a disputed badge or some other visual
        context["is_disputed"] = (
            transaction is not None and transaction.status == TransactionStatus.DISPUTED
        )
        return context


class ChatThreadSendView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    SingleObjectMixin[ChatThread],
    View,
):
    """
    Store one message and return message bubbles after the cursor through to the new message.
    """

    model = ChatThread
    permission_required = ChatThreadOLP.VIEW

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        sender = get_authenticated_user(request)
        chat_thread = self.get_object()
        try:
            after = _parse_cursor(request.POST.get("after"), chat_thread)
        except _InvalidCursor as exc:
            return HttpResponseBadRequest(str(exc))

        try:
            message = MessagingService.send_message(
                chat_thread, sender, request.POST.get("body", "")
            )
        except InvalidMessageBody as exc:
            # Show services.py:MessagingService.send_message wording
            return HttpResponse(str(exc), status=400, content_type="text/plain")
        except ThreadNotWritable:
            # The thread was archived while this message was being typed.
            # services.py:MessagingService.close_prerequest_thread wording includes thread pk.
            return HttpResponse(
                "This conversation is archived.", status=409, content_type="text/plain"
            )

        chat_messages = (
            chat_thread.messages.filter(id__gt=after, id__lte=message.pk)
            .select_related("sender__profile")
            .order_by("id")
        )
        return render(
            request,
            "messaging/_messages.html",
            {"chat_messages": chat_messages, "viewer": sender},
        )


class ChatThreadPollView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    SingleObjectMixin[ChatThread],
    View,
):
    """
    Hand back whatever has been said since the reader's newest message.

    `?after=` is the id of the last bubble currently on the sender's screen.
    `after` is used as the cursor.
    """

    model = ChatThread
    permission_required = ChatThreadOLP.VIEW

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        chat_thread = self.get_object()
        try:
            after = _parse_cursor(request.GET.get("after"), chat_thread)
        except _InvalidCursor as exc:
            return HttpResponseBadRequest(str(exc))

        newer = (
            chat_thread.messages.filter(id__gt=after)
            .select_related("sender__profile")
            .order_by("id")
        )

        # No new messages since last poll? send 204. htmx does not re-render/swap on a 204.
        # https://htmx.org/docs/#requests
        if not newer and not chat_thread.is_archived:
            return HttpResponse(status=204)

        # An archived thread is finished; nobody can write to it again, so hand
        # over whatever the reader is missing and shut the poller down.
        # 286 swaps the body one last time and then cancels polling.
        # The reply also carries a replacement for the typing box
        # see templates/messaging/_composer_archived.html.
        # https://htmx.org/docs/#polling
        return render(
            request,
            "messaging/_poll.html",
            {
                "chat_thread": chat_thread,
                "chat_messages": newer,
                "viewer": get_authenticated_user(request),
            },
            status=286 if chat_thread.is_archived else 200,
        )


class ChatThreadCloseView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    SingleObjectMixin[ChatThread],
    View,
):
    """
    End a pre-request chat that never turned into a request. The thread archives.
    Either party may do this.
    """

    model = ChatThread
    permission_required = ChatThreadOLP.VIEW

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        chat_thread = self.get_object()
        closed_by = get_authenticated_user(request)
        try:
            MessagingService.close_prerequest_thread(chat_thread, closed_by)
        except ThreadNotWritable:
            # Both parties hit close, or the transaction archived the thread first.
            messages.info(request, "This conversation is already closed.")
        except PermissionDenied:
            # The item was requested between rendering the button and pressing it.
            messages.info(
                request, "This conversation belongs to a request now, so it stays open."
            )
        return redirect("chat-thread-detail", pk=chat_thread.pk)


class ChatThreadListView(
    MessagingEnabledMixin,
    LoginRequiredMixin,
    ListView[ChatThread],
):
    """
    Every conversation this user is part of, newest first.
    Deliberately bare bones.
    TODO: update in future pr per #536
    """

    template_name = "messaging/chatthread_list.html"
    context_object_name = "chat_threads"

    def get_queryset(self) -> QuerySet[ChatThread]:
        user = get_authenticated_user(self.request)
        return (
            ChatThread.objects.filter(Q(lender=user) | Q(borrower=user))
            .select_related("item", "lender__profile", "borrower__profile")
            # Sort on the last message, falling back to creation for threads with no msgs
            .annotate(
                last_activity_at=Coalesce(Max("messages__created_at"), "created_at")
            )
            .order_by("-last_activity_at", "-pk")
        )
