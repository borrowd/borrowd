from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.generic import (
    UpdateView,
)

from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_items.models import Item
from borrowd_users.models import Profile


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    # It's annoying that we have to ignore this. The OneToOne field
    # linking Profiles to the User model results in a reciprocal
    # `profile` field added to the User model at runtime, hence
    # not available to mypy. The usual solution is to add an explicit
    # forward declaration on the other end of the relationship, but
    # since this is the User class we're talking about, our options
    # for making that change are limited; it looks like the easiest
    # way would be to replace the default User class wholesale, which
    # in itself is not easy.
    profile = request.user.profile  # type: ignore
    user_items = Item.objects.filter(owner=request.user)
    return render(
        request, "users/profile.html", {"profile": profile, "user_items": user_items}
    )


class ProfileUpdateView(
    LoginRequiredMixin,
    BorrowdTemplateFinderMixin,
    UpdateView[Profile, ModelForm[Profile]],
):
    model = Profile
    fields = ["image"]

    def get_object(self, queryset=None) -> Profile:
        return self.request.user.profile

    def get_success_url(self) -> str:
        return reverse("profile")
