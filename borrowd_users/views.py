from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
)

from borrowd_items.models import Item, ItemStatus, Transaction

from .forms import CustomSignupForm, ProfileUpdateForm
from .models import BorrowdUser


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    user: BorrowdUser = request.user  # type: ignore[assignment]
    profile = user.profile

    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile has been updated successfully.")
            return redirect("profile")
    else:
        form = ProfileUpdateForm(instance=profile)

    return render(
        request,
        "users/profile.html",
        {
            "profile": profile,
            "form": form,
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

        # Honor next parameter if it exists
        if "next" in self.request.GET:
            return redirect(self.request.GET["next"])

        return redirect(self.success_url)

    def form_invalid(self, form: CustomSignupForm) -> HttpResponse:
        """
        Handle form validation errors.
        """
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)
