from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.generic import DetailView, View
from django.views.generic.detail import SingleObjectMixin

from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_permissions.mixins import LoginOr404PermissionMixin
from borrowd_permissions.models import ChatThreadOLP
from borrowd_users.request import get_authenticated_user

from .exceptions import InvalidMessageBody, ThreadNotWritable
from .mixins import MessagingEnabledMixin
from .models import MESSAGE_BODY_MAX_LENGTH, ChatThread
from .services import MessagingService


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
        return super().get_queryset().select_related("item", "lender", "borrower")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = get_authenticated_user(self.request)
        chat_thread = self.object
        context["other_party"] = (
            chat_thread.borrower
            if user.pk == chat_thread.lender_id
            else chat_thread.lender
        )
        # Not "messages": that name belongs to the django.contrib.messages context processor.
        # sender__profile: every bubble reads the sender's avatar and full name.
        context["chat_messages"] = chat_thread.messages.select_related(
            "sender__profile"
        ).order_by("id")
        context["message_body_max_length"] = MESSAGE_BODY_MAX_LENGTH
        return context


class ChatThreadSendView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    SingleObjectMixin[ChatThread],
    View,
):
    """
    Take one typed message and hand back the bubble for it,
    so the sender's own message appears the same way the other party will see it.
    """

    model = ChatThread
    permission_required = ChatThreadOLP.VIEW

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        sender = get_authenticated_user(request)
        try:
            message = MessagingService.send_message(
                self.get_object(), sender, request.POST.get("body", "")
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
        return render(
            request,
            "messaging/_message.html",
            {"message": message, "viewer": sender},
        )
