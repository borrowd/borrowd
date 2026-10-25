from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, QueryDict
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import DetailView, TemplateView, View

from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_items.card_helpers import item_thumbnail_url
from borrowd_items.models import Item, ItemAction, ItemStatus
from borrowd_permissions.mixins import CachedObjectMixin, LoginOr404PermissionMixin
from borrowd_permissions.models import ChatThreadOLP, ItemOLP
from borrowd_users.models import BorrowdUser
from borrowd_users.request import get_authenticated_user

from .conversation_summaries import (
    build_hub_cards,
    conversation_status,
    has_removed_item,
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
from .read_state import (
    cursor_names_message_in_thread,
    mark_thread_read,
    unread_threads_for,
)
from .services import MessagingService

_HUB_PAGE_SIZE = 25
_SCOPES = ("all", "lending", "borrowing")


class _InvalidCursor(ValueError):
    pass


def _parse_cursor(raw_cursor: str | None, chat_thread: ChatThread) -> int:
    message = "`after` must be a message id from this conversation."
    if raw_cursor is None:
        raise _InvalidCursor(message)

    try:
        cursor = int(raw_cursor)
    except ValueError as exc:
        raise _InvalidCursor(message) from exc

    if cursor < 0 or not cursor_names_message_in_thread(chat_thread.pk, cursor):
        raise _InvalidCursor(message)
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
            "item_thumbnail_url": item_thumbnail_url(item)
            if item is not None
            else None,
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
                "messaging/_unread_badge.html",
                {
                    "unread_conversation_count": count,
                    "unread_conversation_label": "conversation"
                    if count == 1
                    else "conversations",
                },
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
        chat_thread = self.get_object()
        error = "`through` must be a message id from this conversation."
        try:
            through = int(request.POST.get("through", ""))
        except ValueError:
            return HttpResponseBadRequest(error)

        # mark_thread_read checks that the cursor names a message in this thread.
        try:
            mark_thread_read(
                chat_thread,
                get_authenticated_user(request),
                through_message_id=through,
            )
        except InvalidReadCursor:
            return HttpResponseBadRequest(error)

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
        viewer = get_authenticated_user(request)
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
                "viewer": viewer,
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
    """Show the viewer's conversations, scoped to All, Lending, or Borrowing."""

    template_name = "messaging/chatthread_list.html"

    def _url(self, base_params: QueryDict, **overrides: str | None) -> str:
        """Build a hub URL from normalized base params, resetting the page."""
        params = base_params.copy()
        for key, value in overrides.items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = value
        params.pop("page", None)
        return f"?{params.urlencode()}"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        viewer = get_authenticated_user(self.request)

        scope = self.request.GET.get("scope")
        if scope not in _SCOPES:
            scope = _SCOPES[0]

        archived_param = self.request.GET.get("archived")
        if archived_param not in {"true", "false"}:
            # Legacy ?section=active|archived, kept working by mapping onto
            # the archived toggle -- the new scope dimension (Lending /
            # Borrowing) has no equivalent in the old URL vocabulary.
            archived_param = (
                "true" if self.request.GET.get("section") == "archived" else "false"
            )
        archived = archived_param == "true"

        # Normalize away the legacy `section` param, so every generated link
        # speaks only the current vocabulary.
        base_params = self.request.GET.copy()
        base_params.pop("section", None)
        base_params["archived"] = archived_param

        filter_data: QueryDict = self.request.GET
        if not filter_data.get("search") and (
            filter_data.get("item") or filter_data.get("person")
        ):
            # Legacy ?item=/?person=, kept working by mapping onto the
            # combined search field -- best effort, since the old two fields
            # could narrow independently and search can only OR across one
            # term list.
            legacy_search = filter_data.get("item") or filter_data.get("person", "")
            filter_data = filter_data.copy()
            filter_data["search"] = legacy_search
            base_params.pop("item", None)
            base_params.pop("person", None)
            base_params["search"] = legacy_search

        all_threads = threads_for_hub(viewer)
        conversations = ConversationFilter(
            filter_data, queryset=all_threads, request=self.request
        )
        filtered_threads = conversations.qs
        filters_applied = any(
            conversations.form.cleaned_data.get(field)
            for field in conversations.filters
        )
        unread_on = bool(conversations.form.cleaned_data.get("unread"))

        visible_threads = filtered_threads.filter(archived_at__isnull=not archived)
        scoped_threads = {
            "all": visible_threads,
            "lending": visible_threads.filter(lender=viewer),
            "borrowing": visible_threads.filter(borrower=viewer),
        }
        shown = scoped_threads[scope]

        page = Paginator(shown, _HUB_PAGE_SIZE).get_page(self.request.GET.get("page"))
        # One aggregate covers all three scope counts, instead of a separate
        # COUNT query per scope.
        scope_counts = visible_threads.aggregate(
            all=Count("pk"),
            lending=Count("pk", filter=Q(lender=viewer)),
            borrowing=Count("pk", filter=Q(borrower=viewer)),
        )
        context["conversation_filter"] = conversations
        context["filters_applied"] = filters_applied
        context["clear_filters_url"] = f"?scope={scope}&archived={archived_param}"
        context["active_scope"] = scope
        context["scope_segments"] = [
            {
                "label": label,
                "url": self._url(base_params, scope=name),
                "count": scope_counts[name],
                "selected": scope == name,
            }
            for name, label in (
                ("all", "All"),
                ("lending", "Lending"),
                ("borrowing", "Borrowing"),
            )
        ]
        if filters_applied:
            empty_state_message = "No conversations match your filters."
        else:
            state = "archived" if archived else "active"
            scope_suffix = "" if scope == "all" else f" {scope}"
            empty_state_message = f"No {state}{scope_suffix} conversations."
        context["empty_state_message"] = empty_state_message
        context["archived"] = archived
        context["unread_on"] = unread_on
        context["unread_toggle_url"] = self._url(
            base_params, scope=scope, unread=None if unread_on else "on"
        )
        context["archived_toggle_url"] = self._url(
            base_params, scope=scope, archived="false" if archived else "true"
        )
        context["page_obj"] = page
        context["cards"] = build_hub_cards(page, viewer)
        # Tell a first-time viewer they have nothing anywhere, not just on this
        # scope. Filters must not hide the form, or there is no way to clear them.
        context["has_conversations"] = all_threads.exists()
        return context
