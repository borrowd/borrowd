from typing import Any
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.messages.api import MessageFailure
from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.datastructures import MultiValueDict
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView
from django_filters.views import FilterView
from guardian.mixins import LoginRequiredMixin

from borrowd.util import BorrowdTemplateFinderMixin, resolve_back_url
from borrowd_groups.models import Membership, MembershipStatus
from borrowd_permissions.mixins import (
    LoginOr403PermissionMixin,
    LoginOr404PermissionMixin,
)
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import SearchTarget, SearchTerm
from borrowd_users.request import get_authenticated_user

from .card_helpers import (
    build_item_card_context,
    build_item_cards_for_items,
)
from .exceptions import InvalidItemAction, ItemAlreadyRequested
from .filters import ItemFilter
from .forms import (
    ALLOWED_IMAGE_ACCEPT,
    ItemCreateWithPhotoForm,
    ItemForm,
    ItemPhotoForm,
)
from .models import Item, ItemAction, ItemPhoto, ItemStatus

_MOBILE_UA_KEYWORDS = ("mobile", "android", "iphone", "ipad", "ipod")

PAGE_SIZE_MOBILE_DEFAULT = 6
PAGE_SIZE_DESKTOP_DEFAULT = 12
PAGE_SIZE_MIN = 4
PAGE_SIZE_MAX = 48


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
        ItemAction.NOTIFY_WHEN_AVAILABLE: "notification requested",
        ItemAction.CANCEL_NOTIFICATION_REQUEST: "notification request canceled",
        ItemAction.RESOLVE_TRANSACTION: "transaction closed out",
        ItemAction.REQUEST_RETURN: "return requested",
        ItemAction.FLAG_CANNOT_RETURN: "flagged as cannot be returned",
        ItemAction.RAISE_DISPUTE: "dispute raised",
        ItemAction.RESOLVE_DISPUTE_RETURNED: "dispute resolved, item returned",
        ItemAction.RESOLVE_DISPUTE_NOT_RETURNED: "dispute resolved, item removed",
        ItemAction.OFFER_GIVEAWAY: "offered as a giveaway",
        ItemAction.ACCEPT_GIVEAWAY: "is now yours",
        ItemAction.DECLINE_GIVEAWAY: "giveaway declined",
        ItemAction.REQUEST_GIVEAWAY: "gift requested",
        ItemAction.APPROVE_GIVEAWAY_REQUEST: "giveaway approved - ownership transferred",
        ItemAction.DECLINE_GIVEAWAY_REQUEST: "gift request declined",
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

    user = get_authenticated_user(request)
    # Resolve against all items, including soft-deleted ones: an owner closing
    # their account soft-eletes their items, but the borrower may still need to
    # close out the stranded loan (RESOLVE_TRANSACTION). The guard below keeps
    # every other action off soft-deleted items.
    item = get_object_or_404(
        Item.all_objects,
        pk=pk,
    )

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

    # A soft-deleted item stays reachable only to close out a stranded loan.
    if item.deleted_at is not None and action != ItemAction.RESOLVE_TRANSACTION:
        return HttpResponse("Not found", status=404)

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
    LoginRequiredMixin,
    BorrowdTemplateFinderMixin,
    CreateView[Item, ItemCreateWithPhotoForm],
):
    model = Item
    form_class = ItemCreateWithPhotoForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = get_authenticated_user(self.request)
        return kwargs

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Add item"
        return context

    def form_valid(self, form: ItemCreateWithPhotoForm) -> HttpResponse:
        user = get_authenticated_user(self.request)
        form.instance.owner = user
        form.instance.created_by = user
        form.instance.updated_by = user
        response = super().form_valid(form)
        image = form.cleaned_data.get("image")
        if image:
            ItemPhoto.objects.create(
                item=form.instance,
                image=image,
                created_by=user,
                updated_by=user,
            )
        return response

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("item-list")
        return reverse("profile-inventory")


class ItemDeleteView(
    LoginOr404PermissionMixin,
    BorrowdTemplateFinderMixin,
    DeleteView[Item, ModelForm[Item]],
):
    model = Item
    permission_required = ItemOLP.DELETE
    success_url = reverse_lazy("profile-inventory")
    http_method_names = ["post"]

    def form_valid(self, form: ModelForm[Item]) -> HttpResponse:
        item: Item = self.object

        if item.status != ItemStatus.AVAILABLE:
            _add_message_safe(
                self.request,
                messages.ERROR,
                "Only available items can be deleted.",
            )
            return redirect("item-detail", pk=item.pk)

        user = get_authenticated_user(self.request)

        item.soft_delete(user)
        _add_message_safe(self.request, messages.SUCCESS, "Item deleted.")
        return redirect(self.get_success_url())


class ItemDetailView(
    LoginOr404PermissionMixin,
    BorrowdTemplateFinderMixin,
    DetailView[Item],
):
    model = Item
    permission_required = ItemOLP.VIEW

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = get_authenticated_user(self.request)

        action_context = self.object.get_action_context_for(user=user)

        """
        build_item_card_context() returns the full template context for item
        cards, including ownership (is_yours), banner styling, action data, etc.
        The detail template relies on these keys, so any detail-specific
        context must be added *after* this call or included in the helper.
        Keep in mind, though that item cards (inventory, search results, etc.)
        also rely on this helper through `build_item_cards_for_items` and
        `build_item_cards_for_transactions`, so make sure to check those for
        compatability when updating the context helper.
        """
        context = build_item_card_context(
            self.object, user, "item-details", action_context
        )

        # URL names (see urls.py) that are valid back-button targets
        allowed_back_button_targets = {
            "item-list",
            "profile-inventory",
        }

        # Back arrow target. depends on how the user got here.
        context["back_url"] = resolve_back_url(
            self.request,
            fallback_url=reverse("item-list"),
            allowed_url_names=allowed_back_button_targets,
        )

        return context


# django-filter is untyped (see the django_filters note in mypy.ini), so
# subclassing FilterView trips strict mode's "subclass of Any" check.
class ItemListView(
    LoginRequiredMixin,
    BorrowdTemplateFinderMixin,
    FilterView,  # type: ignore[misc]
):
    model = Item
    template_name_suffix = "_list"  # Reusing template from ListView
    filterset_class = ItemFilter

    def get_paginate_by(self, queryset: object) -> int:
        ua = self.request.META.get("HTTP_USER_AGENT", "").lower()
        is_mobile = any(kw in ua for kw in _MOBILE_UA_KEYWORDS)
        default = PAGE_SIZE_MOBILE_DEFAULT if is_mobile else PAGE_SIZE_DESKTOP_DEFAULT
        raw = self.request.GET.get("page_size")
        if raw is None:
            return default
        try:
            return max(PAGE_SIZE_MIN, min(PAGE_SIZE_MAX, int(raw)))
        except ValueError:
            return default

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        term = request.GET.get("search")
        if term is not None:
            SearchTerm.record_search(
                user=get_authenticated_user(request),
                target=SearchTarget.ITEMS,
                term=term,
            )
        # super() is FilterView.get, which is Any (see the django_filters note
        # in mypy.ini); annotating pins it to the real return type.
        response: HttpResponse = super().get(request, *args, **kwargs)
        return response

    def get_queryset(self) -> QuerySet[Item]:
        queryset: QuerySet[Item] = super().get_queryset()
        return queryset.prefetch_related("photos")

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)
        user = get_authenticated_user(self.request)

        # Build card contexts for all items
        items = list(context["object_list"])
        context["item_cards"] = build_item_cards_for_items(items, user, "search")
        context["user_has_items"] = Item.objects.filter(
            owner=user,
        ).exists
        context["user_has_groups"] = Membership.objects.filter(
            user=user,
            status=MembershipStatus.ACTIVE,
        ).exists()

        return context


class ItemUpdateView(
    LoginOr404PermissionMixin,
    BorrowdTemplateFinderMixin,
    UpdateView[Item, ItemForm],
):
    model = Item
    permission_required = ItemOLP.EDIT
    form_class = ItemForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = get_authenticated_user(self.request)
        return kwargs

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit item"
        context["photo_accept"] = ALLOWED_IMAGE_ACCEPT
        return context

    def form_valid(self, form: ItemForm) -> HttpResponse:
        form.instance.updated_by = get_authenticated_user(self.request)
        response = super().form_valid(form)
        self._process_uploaded_photos()
        _add_message_safe(self.request, messages.SUCCESS, "Changes saved.")
        return response

    def _process_uploaded_photos(self) -> None:
        """Save any new photos uploaded alongside the edit form."""
        uploaded_files = self.request.FILES.getlist("new_photos")
        if not uploaded_files:
            return

        item: Item = self.object
        user = get_authenticated_user(self.request)
        remaining_slots = 5 - item.photos.count()

        skipped = 0

        for upload in uploaded_files[:remaining_slots]:
            photo_files: MultiValueDict[str, UploadedFile] = MultiValueDict(
                {"image": [upload]}
            )
            photo_form = ItemPhotoForm(files=photo_files)
            if not photo_form.is_valid():
                skipped += 1
                continue
            photo = photo_form.save(commit=False)
            photo.item = item
            photo.created_by = user
            photo.updated_by = user
            photo.save()

        if skipped:
            _add_message_safe(
                self.request,
                messages.WARNING,
                f"{skipped} photo(s) were skipped -- invalid format or over 5 MB.",
            )
        over_limit = len(uploaded_files) - remaining_slots
        if over_limit > 0:
            _add_message_safe(
                self.request,
                messages.WARNING,
                f"{over_limit} photo(s) were skipped -- photo limit (5) reached.",
            )

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("item-list")
        # Land on the edited item's detail page so the user sees their
        # changes applied; `?next=` points its back button at inventory.
        detail_url = reverse("item-detail", args=[self.object.pk])
        next_query = urlencode({"next": reverse("profile-inventory")})
        return f"{detail_url}?{next_query}"


class ItemPhotoCreateView(
    LoginOr403PermissionMixin,
    BorrowdTemplateFinderMixin,
    CreateView[ItemPhoto, ItemPhotoForm],
):
    model = ItemPhoto
    permission_required = ItemOLP.EDIT
    form_class = ItemPhotoForm

    def get_permission_object(self) -> Item:
        return get_object_or_404(Item, pk=self.kwargs["item_pk"])

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        item_pk = self.kwargs["item_pk"]
        context["item_pk"] = item_pk
        context["next"] = self.request.GET.get("next")
        return context

    def form_valid(self, form: ItemPhotoForm) -> HttpResponse:
        context = self.get_context_data()
        user = get_authenticated_user(self.request)
        form.instance.item_id = context["item_pk"]
        form.instance.created_by = user
        form.instance.updated_by = user
        return super().form_valid(form)

    def get_success_url(self) -> str:
        instance: ItemPhoto | None = self.object
        if instance is None:
            return reverse("item-list")

        # Check if a 'next' parameter was provided
        next_url: str | None = self.request.GET.get("next")
        if next_url:
            return next_url

        # Default to item edit page
        return reverse("item-edit", args=[instance.item_id])


class ItemPhotoDeleteView(
    LoginOr403PermissionMixin,
    BorrowdTemplateFinderMixin,
    DeleteView[ItemPhoto, ModelForm[ItemPhoto]],
):
    model = ItemPhoto
    permission_required = ItemOLP.EDIT
    http_method_names = ["post"]

    def get_permission_object(self) -> Item:
        return self.get_object().item

    def form_valid(self, form: ModelForm[ItemPhoto]) -> HttpResponse:
        _add_message_safe(self.request, messages.SUCCESS, "Photo deleted.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        instance: ItemPhoto = self.object
        if instance is None:
            return reverse("item-list")
        return reverse("item-edit", args=[instance.item_id])
