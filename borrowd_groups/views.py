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

from .models import BorrowdGroup


class GroupCreateView(
    BorrowdTemplateFinderMixin, CreateView[BorrowdGroup, ModelForm[BorrowdGroup]]
):
    model = BorrowdGroup
    fields = ["name", "description", "membership_requires_approval"]

    def form_valid(self, form):
        if self.request.user.is_authenticated:
            form.instance.created_by_id = form.instance.updated_by_id = (
                self.request.user.id
            )
        return super().form_valid(form)

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("borrowd_groups:group-list")
        return reverse("borrowd_groups:group-detail", args=[self.object.pk])


class GroupDeleteView(
    BorrowdTemplateFinderMixin, DeleteView[BorrowdGroup, ModelForm[BorrowdGroup]]
):
    # Todo: prevent non-admin/moderators from completing this action
    model = BorrowdGroup
    success_url = reverse_lazy("borrowd_groups:group-list")


class GroupDetailView(BorrowdTemplateFinderMixin, DetailView[BorrowdGroup]):
    model = BorrowdGroup


class GroupListView(BorrowdTemplateFinderMixin, ListView[BorrowdGroup]):
    model = BorrowdGroup


class GroupUpdateView(
    BorrowdTemplateFinderMixin, UpdateView[BorrowdGroup, ModelForm[BorrowdGroup]]
):
    model = BorrowdGroup
    fields = ["name", "description", "membership_requires_approval"]

    def form_valid(self, form):
        if self.request.user.is_authenticated:
            form.instance.updated_by_id = self.request.user.id
        return super().form_valid(form)

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("borrowd_groups:group-list")
        return reverse("borrowd_groups:group-detail", args=[self.object.pk])
