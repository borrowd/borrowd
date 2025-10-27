from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    CreateView,
    UpdateView,
)

from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_items.models import Item, ItemStatus, Transaction
from borrowd_users.models import Profile

from .forms import CustomSignupForm, ProfileUpdateForm
from .models import BorrowdUser


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    user: BorrowdUser = request.user  # type: ignore[assignment]
    profile = user.profile

    return render(
        request,
        "users/profile.html",
        {
            "profile": profile,
        },
    )


@login_required
def inventory_view(request: HttpRequest) -> HttpResponse:
    user: BorrowdUser = request.user  # type: ignore[assignment]

    requests_from_user = Transaction.get_borrow_requests_from_user(user)
    requests_to_user = Transaction.get_borrow_requests_to_user(user)
    borrowed = Transaction.get_current_borrows_for_user(user)
    user_items = Item.objects.filter(owner=user)
    # Add borrower info to user's items that are currently borrowed
    for item in user_items:
        if item.status == ItemStatus.BORROWED:
            tx = item.get_current_transaction_for_user(user)
            if tx:
                item.borrower = tx.party2  # type: ignore[attr-defined]

    return render(
        request,
        "users/inventory.html",
        {
            "requests_from_user": requests_from_user,
            "requests_to_user": requests_to_user,
            "borrowed": borrowed,
            "user_items": user_items,
        },
    )


class ProfileUpdateView(
    LoginRequiredMixin,
    BorrowdTemplateFinderMixin,
    UpdateView[Profile, ProfileUpdateForm],
):
    model = Profile
    form_class = ProfileUpdateForm

    def get_object(self, queryset: QuerySet[Any] | None = None) -> Profile:
        user: BorrowdUser = self.request.user  # type: ignore[assignment]
        return user.profile

    def form_valid(self, form: ProfileUpdateForm) -> HttpResponse:
        """Add success message when profile is updated."""
        messages.success(self.request, "Your profile has been updated successfully.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return reverse("profile")


class CustomSignupView(CreateView[BorrowdUser, CustomSignupForm]):
    """
    Custom signup view that handles user registration with first/last names
    and integrates with allauth for authentication.
    """

    model = BorrowdUser
    form_class = CustomSignupForm
    template_name = "account/signup.html"
    success_url = reverse_lazy("item-list")  # Redirect after successful signup

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """
        Redirect authenticated users away from signup page.
        """
        if request.user.is_authenticated:
            return redirect("item-list")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form: CustomSignupForm) -> HttpResponse:
        """
        Handle successful form submission.
        Create the user and log them in.
        """
        user = form.save()

        # Log the user in immediately after signup with the ModelBackend
        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")

        messages.success(
            self.request, "Welcome! Your account has been created successfully."
        )

        return redirect(self.success_url)

    def form_invalid(self, form: CustomSignupForm) -> HttpResponse:
        """
        Handle form validation errors.
        """
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)
