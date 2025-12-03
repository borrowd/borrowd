from typing import Any

from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView
from django_filters.views import FilterView
from guardian.mixins import LoginRequiredMixin

from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_users.models import BorrowdUser

from .exceptions import InvalidItemAction, ItemAlreadyRequested
from .filters import ItemFilter
from .forms import ItemCreateWithPhotoForm, ItemForm
from .models import Item, ItemAction, ItemPhoto


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

    # mypy complains that `request.user` is a AbstractBaseUser or
    # AnonymousUser, but when I follow the code it looks like it's
    # AbstractUser or AnonymousUser, which we *would* comply with
    # here (BorrowdUser subclasses AbstractUser).
    user: BorrowdUser = request.user  # type: ignore[assignment]

    item = Item.objects.get(pk=pk)

    # Not currently differentiating between viewing and borrowing
    # permissions; assumed that if a user can "see" an item (and
    # they're not the owner), then they can request to borrow it.
    if not user.has_perm("view_this_item", item):
        return HttpResponse(
            "You do not have permission to borrow this item.", status=403
        )

    try:
        req_action = req_action.upper()
        item.process_action(user=user, action=ItemAction(req_action))
        # Action succeeded, return success response
        action_context = item.get_action_context_for(user=user)
        return render(
            request,
            template_name="components/items/action_buttons_with_status.html",
            context={
                "item": item,
                "action_context": action_context,
            },
            content_type="text/html",
            status=200,
        )
    except ItemAlreadyRequested:
        # Specific case: item already requested by another user
        action_context = item.get_action_context_for(user=user)
        return render(
            request,
            template_name="components/items/action_buttons_with_status.html",
            context={
                "item": item,
                "action_context": action_context,
                "error_message": "Sorry! Another user requested this item just before you.",
                "error_type": "already_requested",
            },
            content_type="text/html",
            status=200,
        )
    except InvalidItemAction:
        # Other invalid actions
        action_context = item.get_action_context_for(user=user)
        return render(
            request,
            template_name="components/items/action_buttons_with_status.html",
            context={
                "item": item,
                "action_context": action_context,
            },
            content_type="text/html",
            status=200,
        )
    except Exception as e:
        # This is maybe too much information to surface to end-users.
        # Leaving in for dev, eventually should probably just log it.
        return HttpResponse(
            f"An error occurred while processing the action: {e}", status=500
        )


class ItemCreateView(
    LoginRequiredMixin,  # type: ignore[misc]
    BorrowdTemplateFinderMixin,
    CreateView[Item, ItemCreateWithPhotoForm],
):
    model = Item
    form_class = ItemCreateWithPhotoForm

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
    LoginRequiredMixin,  # type: ignore[misc]
    BorrowdTemplateFinderMixin,
    DeleteView[Item, ModelForm[Item]],
):
    model = Item
    success_url = reverse_lazy("item-list")


class ItemDetailView(
    LoginRequiredMixin,  # type: ignore[misc]
    BorrowdTemplateFinderMixin,
    DetailView[Item],
):
    model = Item

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
    LoginRequiredMixin,  # type: ignore[misc]
    BorrowdTemplateFinderMixin,
    UpdateView[Item, ItemForm],
):
    model = Item
    form_class = ItemForm

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("item-list")
        return reverse("item-detail", args=[self.object.pk])


class ItemPhotoCreateView(
    LoginRequiredMixin,  # type: ignore[misc]
    BorrowdTemplateFinderMixin,
    CreateView[ItemPhoto, ModelForm[ItemPhoto]],
):
    model = ItemPhoto
    fields = ["image"]  # item set from URL params

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        item_pk = self.kwargs["item_pk"]
        context["item_pk"] = item_pk
        return context

    def form_valid(self, form: ModelForm[ItemPhoto]) -> HttpResponse:
        context = self.get_context_data()
        form.instance.item_id = context["item_pk"]
        return super().form_valid(form)

    def get_success_url(self) -> str:
        instance: ItemPhoto = self.object  # type: ignore[assignment]
        if instance is None:
            return
        return reverse("item-edit", args=[instance.item_id])


class ItemPhotoDeleteView(
    LoginRequiredMixin,  # type: ignore[misc]
    BorrowdTemplateFinderMixin,
    DeleteView[ItemPhoto, ModelForm[ItemPhoto]],
):
    model = ItemPhoto

    def get_success_url(self) -> str:
        instance: ItemPhoto = self.object
        if instance is None:
            return
        return reverse("item-edit", args=[instance.item_id])
