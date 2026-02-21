from typing import Any

from django.contrib import messages
from django.contrib.messages.api import MessageFailure
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
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

from .card_helpers import build_item_cards_for_items
from .exceptions import InvalidItemAction, ItemAlreadyRequested
from .filters import ItemFilter
from .forms import ItemCreateWithPhotoForm, ItemForm, ItemPhotoForm
from .models import Item, ItemAction, ItemPhoto


def _build_item_action_success_message(item_name: str, action: ItemAction) -> str:
    """
    Return a user-facing success message for a completed item action.
    """
    action_to_result = {
        ItemAction.REQUEST_ITEM: "requested",
        ItemAction.ACCEPT_REQUEST: "request accepted",
        ItemAction.REJECT_REQUEST: "request declined",
        ItemAction.MARK_COLLECTED: "marked as collected",
        ItemAction.CONFIRM_COLLECTED: "collection confirmed",
        ItemAction.MARK_RETURNED: "marked as returned",
        ItemAction.CONFIRM_RETURNED: "return confirmed",
        ItemAction.CANCEL_REQUEST: "request canceled",
    }
    return f"{item_name} {action_to_result[action]}."


def _add_message_safe(request: HttpRequest, level: int, message_text: str) -> None:
    """
    Add a Django message when message storage is available on the request.
    """
    try:
        messages.add_message(request, level, message_text)
    except MessageFailure:
        # Some unit tests call views directly with RequestFactory requests
        # that skip middleware and therefore have no message storage.
        return


@require_POST
def borrow_item(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Progress the borrowing flow for an Item.

    This POST endpoint requires an `action` parameter, corresponding
    to the py:class:`ItemAction` enum. Core logic is delegated to
    :py:meth:`.models.Item.process_action` and
    :py:meth:`.models.Item.get_actions_for`.

    On success, redirects back to the referring page (or the item
    detail page as a fallback).

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

    # mypy complains that `request.user` is a AbstractBaseUser or
    # AnonymousUser, but when I follow the code it looks like it's
    # AbstractUser or AnonymousUser, which we *would* comply with
    # here (BorrowdUser subclasses AbstractUser).
    user: BorrowdUser = request.user  # type: ignore[assignment]
    item = Item.objects.get(pk=pk)

    # Not currently differentiating between viewing and borrowing
    # permissions; assumed that if a user can "see" an item (and
    # they're not the owner), then they can request to borrow it.
    if not user.has_perm(ItemOLP.VIEW, item):
        return HttpResponse("Not found", status=404)

    # reverse() resolves a URL name to its path, e.g. "item-detail"
    # with pk=42 becomes "/items/42/".
    # https://docs.djangoproject.com/en/5.2/ref/urlresolvers/#reverse
    fallback_url = reverse("item-detail", kwargs={"pk": pk})

    # HTTP_REFERER is the page the user was on when they submitted the form
    # e.g. "/items/?q=drill" or "/inventory/"
    # https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Referer
    redirect_url = request.META.get("HTTP_REFERER", fallback_url)

    try:
        action = ItemAction(req_action.upper())
    except ValueError:
        _add_message_safe(
            request,
            messages.ERROR,
            f"Unknown action for '{item.name}'.",
        )
        return redirect(redirect_url)

    try:
        item.process_action(user=user, action=action)
    except ItemAlreadyRequested:
        _add_message_safe(
            request,
            messages.WARNING,
            "Sorry! Another user requested this item just before you.",
        )
    except InvalidItemAction:
        _add_message_safe(
            request,
            messages.ERROR,
            f"Unable to perform that action on '{item.name}' right now.",
        )
    else:
        _add_message_safe(
            request,
            messages.SUCCESS,
            _build_item_action_success_message(item.name, action),
        )

    return redirect(redirect_url)


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

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        return queryset.prefetch_related("photos")

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)
        user: BorrowdUser = self.request.user

        # Build card contexts for all items
        items = list(context["object_list"])
        context["item_cards"] = build_item_cards_for_items(items, user, "search")

        return context


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
