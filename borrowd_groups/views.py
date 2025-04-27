from django.forms import ModelForm
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from borrowd.util import BorrowdTemplateFinderMixin

from .models import Group


class GroupCreateView(BorrowdTemplateFinderMixin, CreateView[Group, ModelForm[Group]]):
    model = Group
    fields = ["name", "description", "membership_requires_approval"]

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("borrowd_groups:group-list")
        return reverse("borrowd_groups:group-detail", args=[self.object.pk])


class GroupDeleteView(BorrowdTemplateFinderMixin, DeleteView[Group, ModelForm[Group]]):
    model = Group
    success_url = reverse_lazy("borrowd_groups:group-list")


class GroupDetailView(BorrowdTemplateFinderMixin, DetailView[Group]):
    model = Group


class GroupListView(BorrowdTemplateFinderMixin, ListView[Group]):
    model = Group


class GroupUpdateView(BorrowdTemplateFinderMixin, UpdateView[Group, ModelForm[Group]]):
    model = Group
    fields = ["name", "description", "membership_requires_approval"]

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("borrowd_groups:group-list")
        return reverse("borrowd_groups:group-detail", args=[self.object.pk])
