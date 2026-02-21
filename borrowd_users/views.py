from typing import Any

from allauth.account.views import PasswordChangeView
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseBase, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
)

from borrowd_items.models import Item, ItemStatus, Transaction, TransactionStatus

from .forms import ChangePasswordForm, CustomSignupForm, ProfileUpdateForm
from .models import BorrowdUser


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    user: BorrowdUser = request.user  # type: ignore[assignment]
    profile = user.profile

    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated")
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
@require_POST
def delete_profile_photo_view(request: HttpRequest) -> JsonResponse:
    """
    Delete the user's profile photo via AJAX without affecting other form fields.
    As of this writing (Dec 28, 2025), the current photo delete flow pops up
    a modal that the user must confirm before deleting the photo.
    If the user clicks "delete" without this view, the phot is deleted,
    but the entire form is submitted, which means any pending updates the user
    has (email, bio, etc.) are also submitted. To avoid this terrible UX,
    this view is necessary, as it deletes only the avatar and allows the other
    fields to be left as-is. This is also why it returns json rather than an http
    redirect or similar.
    """
    user: BorrowdUser = request.user  # type: ignore[assignment]
    profile = user.profile

    if profile.image:
        profile.image.delete(save=False)
        profile.image = None
        profile.save()
        # Returns json rather than http in order to allow other in-progress fields to be left as-is.
        return JsonResponse(
            {
                "success": True,
                "message": "You deleted your profile picture.",
                "full_name": profile.full_name(),
            }
        )

    return JsonResponse(
        {"success": False, "message": "No profile picture to delete."},
        status=400,
    )


@login_required
def inventory_view(request: HttpRequest) -> HttpResponse:
    """
    Inventory page with users own items and currently requested/borrowed items

    Data is organized for a toggle UI:
    - Toggle ON (Your Items): Shows owned items only
    - Toggle OFF (All Items): Shows all activity including borrowed items

    Separated into following sections:
    items_needing_approval: user-owned items that have been requested to be borrowed
    owned_items_borrowed: user-owned items that are currently being borrowed out (not available)
    owned_items_available: user-owned items that are available to be borrowed (not requested)
    user_requested_items: items the current user has requested to borrow from others
    user_borrowed_items: items the current user is currently borrowing from others
    """
    user: BorrowdUser = request.user  # type: ignore[assignment]

    # Items needing approval: pending requests where user is the owner (party1)
    items_needing_approval = Transaction.objects.filter(
        party1=user,
        status=TransactionStatus.REQUESTED,
    ).select_related("item", "party2", "party2__profile")

    # User-owned items that are currently being borrowed out (not available)
    owned_items_borrowed = Item.objects.filter(
        owner=user,
        status__in=[ItemStatus.RESERVED, ItemStatus.BORROWED],
    ).prefetch_related("photos")

    # Add borrower info to borrowed items
    for item in owned_items_borrowed:
        tx = item.get_current_transaction_for_user(user)
        if tx:
            item.borrower = tx.party2  # type: ignore[attr-defined]

    # Owned items that are available for borrowing
    owned_items_available = Item.objects.filter(
        owner=user,
        status=ItemStatus.AVAILABLE,
    ).prefetch_related("photos")

    # Items user has requested from others (pending requests)
    user_requested_items = Transaction.objects.filter(
        party2=user,
        status__in=[
            TransactionStatus.REQUESTED,
            TransactionStatus.ACCEPTED,
            TransactionStatus.COLLECTION_ASSERTED,
        ],
    ).select_related("item", "party1", "party1__profile", "item__owner")

    # Items user is currently borrowing
    user_borrowed_items = Transaction.objects.filter(
        party2=user,
        status__in=[
            TransactionStatus.COLLECTED,
            TransactionStatus.RETURN_ASSERTED,
        ],
    ).select_related("item", "party1", "party1__profile", "item__owner")

    # Boolean flags for empty state detection
    has_owned_items = (
        owned_items_borrowed.exists()
        or owned_items_available.exists()
        or items_needing_approval.exists()
    )
    has_activity = user_requested_items.exists() or user_borrowed_items.exists()

    return render(
        request,
        "users/inventory.html",
        {
            "items_needing_approval": items_needing_approval,
            "owned_items_borrowed": owned_items_borrowed,
            "owned_items_available": owned_items_available,
            "user_requested_items": user_requested_items,
            "user_borrowed_items": user_borrowed_items,
            "has_owned_items": has_owned_items,
            "has_activity": has_activity,
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
    success_url = reverse_lazy("onboarding_step1")  # Redirect after successful signup

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

        next_url = self.request.GET.get("next")
        if next_url:
            self.request.session["post_onboarding_redirect"] = next_url

        return redirect(self.success_url)

    def form_invalid(self, form: CustomSignupForm) -> HttpResponse:
        """
        Handle form validation errors.
        """
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class CustomPasswordChangeView(PasswordChangeView):  # type: ignore[misc]
    """
    Custom password change view that displays validation errors as warning toasts.

    Extends allauth's PasswordChangeView to add a warning message when form
    validation fails. This ensures users see an orange toast notification
    per ux.
    """

    def form_invalid(self, form: ChangePasswordForm) -> HttpResponse:
        """Add warning message when password validation fails."""
        # Get the first error message to display in the toast
        error_message: str | None = None
        for field in form:
            if field.errors:
                error_message = str(field.errors[0])
                break
        if not error_message and form.non_field_errors():
            error_message = str(form.non_field_errors()[0])

        if error_message:
            messages.warning(self.request, error_message)

        return super().form_invalid(form)  # type: ignore[no-any-return]
