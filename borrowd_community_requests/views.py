from typing import Any, cast

from django.contrib import messages
from django.db.models import QuerySet
from django.http import HttpResponse
from django.urls import reverse
from django.views.generic import CreateView, DetailView
from guardian.mixins import LoginRequiredMixin

from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_users.models import BorrowdUser

from .forms import CommunityRequestForm
from .models import CommunityRequest


class CommunityRequestCreateView(
    LoginRequiredMixin,
    BorrowdTemplateFinderMixin,
    CreateView[CommunityRequest, CommunityRequestForm],
):
    model = CommunityRequest
    form_class = CommunityRequestForm

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        item_name = self.request.GET.get("item_name") or self.request.GET.get("search")

        if item_name:
            initial["item_name"] = item_name[:50]

        return initial

    def get_form(
        self,
        form_class: type[CommunityRequestForm] | None = None,
    ) -> CommunityRequestForm:
        form = super().get_form(form_class)
        form.instance.requester = cast(BorrowdUser, self.request.user)
        return form

    def form_valid(self, form: CommunityRequestForm) -> HttpResponse:
        messages.success(self.request, "Your request has been made")
        return super().form_valid(form)

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Create a request"
        return context

    def get_success_url(self) -> str:
        assert self.object is not None
        return reverse(
            "community-request-success",
            kwargs={"pk": self.object.pk},
        )


class CommunityRequestSuccessView(
    LoginRequiredMixin,
    DetailView[CommunityRequest],
):
    model = CommunityRequest
    template_name = "community_requests/communityrequest_success.html"
    context_object_name = "community_request"

    def get_queryset(self) -> QuerySet[CommunityRequest]:
        user = cast(BorrowdUser, self.request.user)
        return CommunityRequest.objects.owned_by(user)

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Item request"
        return context
