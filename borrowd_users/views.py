from typing import Any

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.generic import (
    UpdateView,
)

from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_items.models import Item, Transaction
from borrowd_users.models import Profile

from .models import BorrowdUser


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    user: BorrowdUser = request.user  # type: ignore[assignment]
    profile = user.profile

    user_items = Item.objects.filter(owner=user)
    lends = Transaction.get_current_lends_for_user(user)
    borrows = Transaction.get_current_borrows_for_user(user)
    return render(
        request,
        "users/profile.html",
        {
            "profile": profile,
            "user_items": user_items,
            "lends": lends,
            "borrows": borrows,
        },
    )


class ProfileUpdateView(
    LoginRequiredMixin,
    BorrowdTemplateFinderMixin,
    UpdateView[Profile, ModelForm[Profile]],
):
    model = Profile
    fields = ["image"]

    def get_object(self, queryset: QuerySet[Any] | None = None) -> Profile:
        user: BorrowdUser = self.request.user  # type: ignore[assignment]
        return user.profile

    def get_success_url(self) -> str:
        return reverse("profile")
