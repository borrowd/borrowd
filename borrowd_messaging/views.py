from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import DetailView, TemplateView, View

from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_items.models import Item, ItemAction, ItemStatus
from borrowd_permissions.mixins import CachedObjectMixin, LoginOr404PermissionMixin
from borrowd_permissions.models import ChatThreadOLP, ItemOLP
from borrowd_users.models import BorrowdUser
from borrowd_users.request import get_authenticated_user

from .conversation_summaries import (
    build_hub_cards,
    conversation_status,
    has_removed_item,
    item_thumbnail_url,
    listed_item,
    threads_for_hub,
)
from .exceptions import (
    ConversationGroupSelectionRequired,
    InvalidConversationGroup,
    InvalidMessageBody,
    InvalidReadCursor,
    PreRequestChatUnavailable,
    ThreadNotWritable,
)
from .filters import ConversationFilter
from .mixins import MessagingEnabledMixin
from .models import MESSAGE_BODY_MAX_LENGTH, ChatThread
from .read_state import mark_thread_read, unread_threads_for
from .services import MessagingService

_INVALID_CURSOR_MESSAGE = "`after` must be a message id from this conversation."
_HUB_PAGE_SIZE = 25
_HUB_SECTIONS = ("active", "archived")


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


class ChatThreadPreRequestOpenView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    CachedObjectMixin[Item],
    View,
):
    """Create or resume the borrower's pre-request conversation for an Item."""

    model = Item
    permission_required = ItemOLP.VIEW
    pk_url_kwarg = "item_pk"
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


@method_decorator(ensure_csrf_cookie, name="dispatch")
class ChatThreadDetailView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    CachedObjectMixin[ChatThread],
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
        context["other_participant"] = (
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
        context["pre_request_action"] = self._pre_request_action(chat_thread, user)
        context.update(self._item_preview(chat_thread, user))
        return context

    @staticmethod
    def _item_preview(
        chat_thread: ChatThread,
        user: BorrowdUser,
    ) -> dict[str, Any]:
        """The Item context pinned above the conversation."""
        item = chat_thread.item
        listed = listed_item(chat_thread)
        status_label, status_kind = conversation_status(chat_thread)
        return {
            "item_name": item.name if item is not None else None,
            "item_thumbnail_url": item_thumbnail_url(item),
            "item_removed": has_removed_item(chat_thread),
            # Link only where the viewer may actually go: a removed Item 404s,
            # and so does one whose group the viewer has since left.
            "item_url": reverse("item-detail", args=[listed.pk])
            if listed is not None and user.has_perm(ItemOLP.VIEW, listed)
            else None,
            "conversation_status_label": status_label,
            "conversation_status_kind": status_kind,
        }

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


@method_decorator(never_cache, name="dispatch")
class ChatThreadUnreadBadgeView(MessagingEnabledMixin, LoginRequiredMixin, View):
    """Return only the viewer's badge contents, without page context processors."""

    http_method_names = ["get"]
    # A fragment request must not swap a redirected login page into the menu.
    raise_exception = True

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        count = unread_threads_for(get_authenticated_user(request)).count()
        return HttpResponse(
            render_to_string(
                "messaging/_unread_badge.html", {"unread_conversation_count": count}
            )
        )


class ChatThreadReadView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    CachedObjectMixin[ChatThread],
    View,
):
    """Acknowledge the browser's rendered boundary, including archived threads."""

    model = ChatThread
    permission_required = ChatThreadOLP.VIEW
    http_method_names = ["post"]

    def get_queryset(self) -> QuerySet[ChatThread]:
        viewer = get_authenticated_user(self.request)
        return super().get_queryset().filter(Q(lender=viewer) | Q(borrower=viewer))

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        raw_cursor = request.POST.get("through")
        try:
            if raw_cursor is None:
                raise ValueError
            through = int(raw_cursor)
        except ValueError:
            return HttpResponseBadRequest("`through` must be a message id.")

        try:
            mark_thread_read(
                self.get_object(),
                get_authenticated_user(request),
                through_message_id=through,
            )
        except InvalidReadCursor as exc:
            return HttpResponseBadRequest(str(exc))

        response = HttpResponse(status=204)
        response["HX-Trigger"] = "messaging:read"
        return response


class ChatThreadSendView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    CachedObjectMixin[ChatThread],
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
    CachedObjectMixin[ChatThread],
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

        # get_object() read this thread fresh, so its status is current: a
        # dispute raised or resolved mid-conversation reaches the reader here.
        status_label, status_kind = conversation_status(chat_thread)

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
                "conversation_status_label": status_label,
                "conversation_status_kind": status_kind,
                "viewer": get_authenticated_user(request),
            },
            status=286 if chat_thread.is_archived else 200,
        )


class ChatThreadPreRequestCloseView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    CachedObjectMixin[ChatThread],
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
    TemplateView,
):
    """Show the viewer's conversations under an Active or Archived tab."""

    template_name = "messaging/chatthread_list.html"

    def _tab_url(self, section: str) -> str:
        """Keep the filters when switching tabs, but start again at page one."""
        params = self.request.GET.copy()
        params["section"] = section
        params.pop("page", None)
        return f"?{params.urlencode()}"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        viewer = get_authenticated_user(self.request)
        selected = self.request.GET.get("section")
        if selected not in _HUB_SECTIONS:
            selected = _HUB_SECTIONS[0]

        all_threads = threads_for_hub(viewer)
        conversations = ConversationFilter(
            self.request.GET, queryset=all_threads, request=self.request
        )
        filters_applied = any(
            conversations.form.data.get(field) for field in conversations.filters
        )
        threads = conversations.qs
        active = threads.filter(archived_at__isnull=True)
        archived = threads.filter(archived_at__isnull=False)
        shown, hidden = (
            (active, archived) if selected == "active" else (archived, active)
        )

        page = Paginator(shown, _HUB_PAGE_SIZE).get_page(self.request.GET.get("page"))
        context["conversation_filter"] = conversations
        context["filters_applied"] = filters_applied
        context["clear_filters_url"] = f"?section={selected}"
        context["conversation_tabs"] = [
            {
                "name": name,
                "title": name.title(),
                "is_selected": name == selected,
                "url": self._tab_url(name),
            }
            for name in _HUB_SECTIONS
        ]
        context["selected_section"] = selected
        context["page_obj"] = page
        context["cards"] = build_hub_cards(page, viewer)
        # Tell a first-time viewer they have nothing anywhere, not just on this
        # tab. Filters must not hide the form, or there is no way to clear them.
        context["has_conversations"] = (
            bool(page.paginator.count)
            or hidden.exists()
            or (filters_applied and all_threads.exists())
        )
        return context
