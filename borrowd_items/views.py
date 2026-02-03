from typing import Any

from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView
from django_filters.views import FilterView
from guardian.mixins import LoginRequiredMixin

from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_permissions.mixins import (
    LoginOr403PermissionMixin,
    LoginOr404PermissionMixin,
)
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser

from .card_helpers import build_item_card_context, parse_card_target
from .exceptions import InvalidItemAction, ItemAlreadyRequested
from .filters import ItemFilter
from .forms import ItemCreateWithPhotoForm, ItemForm, ItemPhotoForm
from .models import Item, ItemAction, ItemActionContext, ItemPhoto


@require_POST
def borrow_item(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Progress the borrowing flow for an Item.

    This POST endpoint requires an `action` parameter, corresponding
    to the py:class:`ItemAction` enum. Core logic is delegated to
    :py:meth:`.models.Item.process_action` and
    :py:meth:`.models.Item.get_actions_for`.

    On success, after progressing the borrowing workflow - which may
    entail updates to both the Item *and* associated an Transaction -
    an updated set of action buttons are returned to the client as
    HTML. This is intended to be used in conjunction with a
    hypermedia library like HTMX, Alpine.js, Datastar, etc.

    Raises:
        InvalidItemAction: If the provided action is not valid for
        the Item in question, for this particular user, for this
        point in the workflow.

    See Also:
        :py:class:`~.models.ItemAction`: Enum of possible actions
        that can be performed on an Item.

    """
    req_action = request.POST.get("action")
    if req_action is None:
        return HttpResponse("No action specified.", status=400)

    user: BorrowdUser = request.user  # type: ignore[assignment]
    item = Item.objects.get(pk=pk)

    if not user.has_perm(ItemOLP.VIEW, item):
        return HttpResponse("Not found", status=404)

    # Parse HX-Target to determine if this is a card request
    hx_target = request.headers.get("HX-Target", "")
    is_card_request, card_context = parse_card_target(hx_target)

    # Choose template and context builder based on request type
    if is_card_request:
        template = "components/items/item_card.html"

        def build_context(
            action_context: ItemActionContext,
            error_message: str | None = None,
            error_type: str | None = None,
        ) -> dict[str, Any]:
            return build_item_card_context(
                item, user, card_context, action_context, error_message, error_type
            )
    else:
        template = "components/items/action_buttons_with_status.html"

        def build_context(
            action_context: ItemActionContext,
            error_message: str | None = None,
            error_type: str | None = None,
        ) -> dict[str, Any]:
            ctx: dict[str, Any] = {"item": item, "action_context": action_context}
            if error_message:
                ctx["error_message"] = error_message
                ctx["error_type"] = error_type
            return ctx

    def render_response(
        action_context: ItemActionContext,
        error_message: str | None = None,
        error_type: str | None = None,
    ) -> HttpResponse:
        response = render(
            request,
            template_name=template,
            context=build_context(action_context, error_message, error_type),
            content_type="text/html",
            status=200,
        )
        response["HX-Trigger"] = f"item-updated-{pk}"
        return response

    try:
        req_action = req_action.upper()
        item.process_action(user=user, action=ItemAction(req_action))
        return render_response(item.get_action_context_for(user=user))
    except ItemAlreadyRequested:
        return render_response(
            item.get_action_context_for(user=user),
            error_message="Sorry! Another user requested this item just before you.",
            error_type="already_requested",
        )
    except InvalidItemAction:
        return render_response(item.get_action_context_for(user=user))
    except Exception as e:
        return HttpResponse(
            f"An error occurred while processing the action: {e}", status=500
        )


@require_GET
def get_item_card(request: HttpRequest, pk: int) -> HttpResponse:
    """GET endpoint to fetch a single item card for HTMX refresh."""
    user: BorrowdUser = request.user  # type: ignore[assignment]
    context = request.GET.get("context", "items")

    try:
        item = Item.objects.get(pk=pk)
    except Item.DoesNotExist:
        return HttpResponse("Not found", status=404)

    if not user.has_perm(ItemOLP.VIEW, item):
        return HttpResponse("Not found", status=404)

    return render(
        request,
        template_name="components/items/item_card.html",
        context=build_item_card_context(item, user, context),
        content_type="text/html",
        status=200,
    )


class ItemCreateView(
    LoginRequiredMixin,  # type: ignore[misc]
    BorrowdTemplateFinderMixin,
    CreateView[Item, ItemCreateWithPhotoForm],
):
    model = Item
    form_class = ItemCreateWithPhotoForm

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Create Item"
        return context

    def form_valid(self, form: ItemCreateWithPhotoForm) -> HttpResponse:
        form.instance.owner = self.request.user  # type: ignore[assignment]
        response = super().form_valid(form)
        image = form.cleaned_data.get("image")
        if image:
            ItemPhoto.objects.create(item=self.object, image=image)
        return response

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("item-list")
        return reverse("item-detail", args=[self.object.pk])


class ItemDeleteView(
    LoginOr404PermissionMixin,
    BorrowdTemplateFinderMixin,
    DeleteView[Item, ModelForm[Item]],
):
    model = Item
    permission_required = ItemOLP.DELETE
    success_url = reverse_lazy("item-list")


class ItemDetailView(
    LoginOr404PermissionMixin,
    BorrowdTemplateFinderMixin,
    DetailView[Item],
):
    model = Item
    permission_required = ItemOLP.VIEW

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user: BorrowdUser = self.request.user  # type: ignore[assignment]
        action_context = self.object.get_action_context_for(user=user)
        context["action_context"] = action_context
        return context


# No typing for django_filter, so mypy doesn't like us subclassing.
class ItemListView(
    LoginRequiredMixin,  # type: ignore[misc]
    BorrowdTemplateFinderMixin,
    FilterView,  # type: ignore[misc]
):
    model = Item
    template_name_suffix = "_list"  # Reusing template from ListView
    filterset_class = ItemFilter


class ItemUpdateView(
    LoginOr404PermissionMixin,
    BorrowdTemplateFinderMixin,
    UpdateView[Item, ItemForm],
):
    model = Item
    permission_required = ItemOLP.EDIT
    form_class = ItemForm

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit Item"
        return context

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("item-list")
        return reverse("item-detail", args=[self.object.pk])


class ItemPhotoCreateView(
    LoginOr403PermissionMixin,
    BorrowdTemplateFinderMixin,
    CreateView[ItemPhoto, ItemPhotoForm],
):
    model = ItemPhoto
    permission_required = ItemOLP.EDIT
    form_class = ItemPhotoForm

    def get_permission_object(self):  # type: ignore[no-untyped-def]
        return Item.objects.get(pk=self.kwargs["item_pk"])

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        item_pk = self.kwargs["item_pk"]
        context["item_pk"] = item_pk
        return context

    def form_valid(self, form: ItemPhotoForm) -> HttpResponse:
        context = self.get_context_data()
        form.instance.item_id = context["item_pk"]
        return super().form_valid(form)

    def get_success_url(self) -> str:
        instance: ItemPhoto = self.object  # type: ignore[assignment]
        if instance is None:
            return
        return reverse("item-edit", args=[instance.item_id])


class ItemPhotoDeleteView(
    LoginOr403PermissionMixin,
    BorrowdTemplateFinderMixin,
    DeleteView[ItemPhoto, ModelForm[ItemPhoto]],
):
    model = ItemPhoto
    permission_required = ItemOLP.EDIT

    def get_permission_object(self):  # type: ignore[no-untyped-def]
        return self.get_object().item

    def get_success_url(self) -> str:
        instance: ItemPhoto = self.object
        if instance is None:
            return
        return reverse("item-edit", args=[instance.item_id])
