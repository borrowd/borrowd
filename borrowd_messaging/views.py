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
from borrowd_items.models import Item, ItemAction, ItemStatus, TransactionStatus
from borrowd_permissions.mixins import LoginOr404PermissionMixin
from borrowd_permissions.models import ChatThreadOLP, ItemOLP
from borrowd_users.models import BorrowdUser
from borrowd_users.request import get_authenticated_user

from .exceptions import (
    ConversationGroupSelectionRequired,
    InvalidConversationGroup,
    InvalidMessageBody,
    PreRequestChatUnavailable,
    ThreadNotWritable,
)
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


class _CachedChatThreadMixin(SingleObjectMixin[ChatThread]):
    """Reuse the ChatThread resolved during the object-permission check."""

    object: ChatThread

    def get_object(self, queryset: QuerySet[ChatThread] | None = None) -> ChatThread:
        if hasattr(self, "object"):
            return self.object
        self.object = super().get_object(queryset)
        return self.object


class _CachedItemMixin(SingleObjectMixin[Item]):
    """Reuse the Item resolved during the object-permission check."""

    object: Item
    pk_url_kwarg = "item_pk"

    def get_object(self, queryset: QuerySet[Item] | None = None) -> Item:
        if hasattr(self, "object"):
            return self.object
        self.object = super().get_object(queryset)
        return self.object


class ChatThreadPreRequestOpenView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    _CachedItemMixin,
    View,
):
    """Create or resume the borrower's pre-request conversation for an Item."""

    model = Item
    permission_required = ItemOLP.VIEW
    http_method_names = ["post"]

    def get_queryset(self) -> QuerySet[Item]:
        return super().get_queryset().select_related("owner__profile")

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        borrower = get_authenticated_user(request)
        item = self.get_object()

        try:
            selected_group = MessagingService.conversation_group_selection(
                request.POST.get("conversation_group")
            )
            chat_thread = MessagingService.get_or_create_prerequest_thread(
                borrower,
                item,
                selected_group=selected_group,
            )
        except (
            ConversationGroupSelectionRequired,
            InvalidConversationGroup,
            PreRequestChatUnavailable,
        ) as exc:
            messages.error(request, str(exc))
            return redirect("item-detail", pk=item.pk)

        return redirect("chat-thread-detail", pk=chat_thread.pk)


class ChatThreadDetailView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    _CachedChatThreadMixin,
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
            .select_related(
                "item",
                "lender__profile",
                "borrower__profile",
                "transaction",
            )
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
        context["is_disputed"] = (
            transaction is not None and transaction.status == TransactionStatus.DISPUTED
        )
        context["pre_request_action"] = self._pre_request_action(chat_thread, user)
        return context

    @staticmethod
    def _pre_request_action(
        chat_thread: ChatThread,
        user: BorrowdUser,
    ) -> ItemAction | None:
        item = chat_thread.item
        if (
            chat_thread.is_archived
            or chat_thread.transaction_id is not None
            or user.pk != chat_thread.borrower_id
            or item is None
            or item.deleted_at is not None
            or item.status != ItemStatus.AVAILABLE
            or item.owner_id != chat_thread.lender_id
            or not user.has_perm(ItemOLP.VIEW, item)
        ):
            return None

        actions = item.get_actions_for(user)
        for request_action in (
            ItemAction.REQUEST_ITEM,
            ItemAction.REQUEST_GIVEAWAY,
        ):
            if request_action in actions:
                return request_action
        return None


class ChatThreadSendView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    _CachedChatThreadMixin,
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
    _CachedChatThreadMixin,
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

        is_disputed = (
            chat_thread.transaction_id is not None
            and ChatThread.objects.filter(
                pk=chat_thread.pk,
                transaction__status=TransactionStatus.DISPUTED,
            ).exists()
        )

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
                "is_disputed": is_disputed,
                "viewer": get_authenticated_user(request),
            },
            status=286 if chat_thread.is_archived else 200,
        )


class ChatThreadPreRequestCloseView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    _CachedChatThreadMixin,
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
    """List every conversation the user participates in, newest activity first."""

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
