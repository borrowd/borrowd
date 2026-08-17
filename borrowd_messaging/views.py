from typing import Any

from django.db.models import QuerySet
from django.views.generic import DetailView

from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_permissions.mixins import LoginOr404PermissionMixin
from borrowd_permissions.models import ChatThreadOLP
from borrowd_users.request import get_authenticated_user

from .mixins import MessagingEnabledMixin
from .models import ChatThread


class ChatThreadDetailView(
    MessagingEnabledMixin,
    LoginOr404PermissionMixin,
    BorrowdTemplateFinderMixin,
    DetailView[ChatThread],
):
    model = ChatThread
    context_object_name = "thread"
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
        return context
