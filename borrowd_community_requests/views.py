from typing import Any, cast

from django.contrib import messages
from django.db.models import Case, Count, IntegerField, Q, QuerySet, Value, When
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import CreateView, DetailView, TemplateView, View
from guardian.mixins import LoginRequiredMixin

from borrowd.util import (
    BROWSABLE_BACK_TARGETS,
    BorrowdTemplateFinderMixin,
    resolve_back_url,
)
from borrowd_community_requests.card_helper import build_commmunity_request_card
from borrowd_users.models import BorrowdUser
from borrowd_users.request import get_authenticated_user

from .exceptions import CannotActOnOwnRequestException
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
        # We land here straight after the create form is submitted, so
        # history.back() would drop the user back into the form they just
        # filled in. The request list is the sane place to go instead.
        context["back_url"] = resolve_back_url(
            self.request,
            fallback_url=reverse("community-request-list"),
            allowed_url_names=BROWSABLE_BACK_TARGETS,
        )
        return context


class CommunityRequestListView(
    LoginRequiredMixin,
    BorrowdTemplateFinderMixin,
    TemplateView,
):
    # TemplateView doesn't set model/template_name_suffix the way
    # ListView/DetailView do, but BorrowdTemplateFinderMixin.get_template_names()
    # relies on both to resolve the template path.
    model = CommunityRequest
    template_name_suffix = "_list"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = get_authenticated_user(self.request)

        scope = self.request.GET.get("scope")
        if scope not in {"all", "yours"}:
            # Legacy ?tab=mine|all, kept working by mapping onto scope.
            scope = "yours" if self.request.GET.get("tab") == "mine" else "all"

        all_requests = CommunityRequest.objects.select_related("requester").visible_to(
            user
        )
        yours_requests = (
            CommunityRequest.objects.select_related("requester").owned_by(user).open()
        )

        if scope == "yours":
            community_requests: QuerySet[CommunityRequest] = yours_requests
        else:
            # The viewer's own requests that already have a response surface
            # first, so they notice lenders are waiting on them; everything
            # else stays newest first.
            community_requests = (
                all_requests.annotate(
                    response_count=Count("responses", distinct=True),
                )
                .annotate(
                    own_with_response=Case(
                        When(
                            Q(requester=user) & Q(response_count__gt=0),
                            then=Value(0),
                        ),
                        default=Value(1),
                        output_field=IntegerField(),
                    )
                )
                .order_by("own_with_response", "-created_at")
            )

        requests_cards_context = [
            build_commmunity_request_card(request, viewing_user=user)
            for request in community_requests
        ]
        context["active_scope"] = scope
        context["scope_segments"] = [
            {
                "label": "All",
                "url": f"{reverse('community-request-list')}?scope=all",
                "count": all_requests.count(),
                "selected": scope == "all",
            },
            {
                "label": "Yours",
                "url": f"{reverse('community-request-list')}?scope=yours",
                "count": yours_requests.count(),
                "selected": scope == "yours",
            },
        ]
        context["community_requests"] = requests_cards_context
        context["page_title"] = "Community requests"
        context["back_url"] = resolve_back_url(
            self.request,
            fallback_url=reverse("item-list"),
            allowed_url_names=BROWSABLE_BACK_TARGETS,
        )
        return context


class CommunityRequestCancelView(LoginRequiredMixin, View):
    """
    Cancel the current user's own open community request.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        user = get_authenticated_user(request)
        community_request = get_object_or_404(
            CommunityRequest.objects.owned_by(user).open(), pk=pk
        )
        community_request.cancel()
        messages.success(request, "Your request has been cancelled.")
        return redirect(f"{reverse('community-request-list')}?scope=yours")


class CommunityRequestMarkFulfilledView(LoginRequiredMixin, View):
    """
    Let the requester explicitly mark their own open community request as
    fulfilled, distinct from cancelling it.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        user = get_authenticated_user(request)
        community_request = get_object_or_404(
            CommunityRequest.objects.owned_by(user).open(), pk=pk
        )
        community_request.mark_fulfilled()
        messages.success(request, "Your request has been marked as fulfilled.")
        return redirect(f"{reverse('community-request-list')}?scope=yours")


class CommunityRequestDismissView(LoginRequiredMixin, View):
    """
    Hide an open community request from the current user's "Requests" tab,
    without affecting its visibility to anyone else.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        user = get_authenticated_user(request)
        community_request = get_object_or_404(
            CommunityRequest.objects.visible_to(user), pk=pk
        )

        try:
            community_request.dismiss_for(user)
        except CannotActOnOwnRequestException:
            messages.error(request, "You can't hide your own request.")
        else:
            messages.success(request, "Request hidden.")

        return redirect("community-request-list")
