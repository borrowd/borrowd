from django.forms import ModelForm
from django.http import HttpResponse
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    UpdateView,
)
from django_filters.views import FilterView

from borrowd.models import TrustLevel
from borrowd.util import BorrowdTemplateFinderMixin

from .filters import ItemFilter
from .models import Item, ItemPhoto


class ItemCreateView(BorrowdTemplateFinderMixin, CreateView[Item, ModelForm[Item]]):
    model = Item
    fields = ["name", "description", "category"]

    def form_valid(self, form: ModelForm[Item]) -> HttpResponse:
        form.instance.owner = self.request.user  # type: ignore[assignment]
        # default trust level for now
        form.instance.trust_level_required = TrustLevel.LOW
        return super().form_valid(form)

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("item-list")
        return reverse("item-detail", args=[self.object.pk])


class ItemDeleteView(BorrowdTemplateFinderMixin, DeleteView[Item, ModelForm[Item]]):
    model = Item
    success_url = reverse_lazy("item-list")


class ItemDetailView(BorrowdTemplateFinderMixin, DetailView[Item]):
    model = Item


# No typing for django_filter, so mypy doesn't like us subclassing.
class ItemListView(BorrowdTemplateFinderMixin, FilterView):  # type: ignore[misc]
    model = Item
    template_name_suffix = "_list"  # Reusing template from ListView
    filterset_class = ItemFilter


class ItemUpdateView(BorrowdTemplateFinderMixin, UpdateView[Item, ModelForm[Item]]):
    model = Item
    fields = ["name", "description", "category"]

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("item-list")
        return reverse("item-detail", args=[self.object.pk])


class ItemPhotoCreateView(BorrowdTemplateFinderMixin, CreateView[ItemPhoto, ModelForm[ItemPhoto]]):
    model = ItemPhoto
    fields = ["image"]  # item set from URL params
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item_pk = self.kwargs["item_pk"]
        context["item_pk"] = item_pk
        return context
    
    def form_valid(self, form: ModelForm[ItemPhoto]) -> HttpResponse:
        context = self.get_context_data()
        form.instance.item_id = context["item_pk"]
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return reverse("item-edit", args=[self.object.item.pk])

class ItemPhotoDeleteView(BorrowdTemplateFinderMixin, DeleteView[ItemPhoto, ModelForm[ItemPhoto]]):
    model = ItemPhoto

    def get_success_url(self) -> str:
        return reverse("item-edit", args=[self.object.item.pk])