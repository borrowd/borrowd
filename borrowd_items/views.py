from django.forms import ModelForm
from django.http import HttpResponse
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from borrowd.models import TrustLevel
from borrowd.util import BorrowdTemplateFinderMixin

from .models import Item


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


class ItemListView(BorrowdTemplateFinderMixin, ListView[Item]):
    model = Item


class ItemUpdateView(BorrowdTemplateFinderMixin, UpdateView[Item, ModelForm[Item]]):
    model = Item
    fields = ["name", "description", "category"]

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("item-list")
        return reverse("item-detail", args=[self.object.pk])
