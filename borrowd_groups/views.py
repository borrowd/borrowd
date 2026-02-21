from collections import namedtuple
from typing import Any

# from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.signing import SignatureExpired, TimestampSigner
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView, View
from django_filters.views import FilterView
from guardian.mixins import LoginRequiredMixin

from borrowd.models import TrustLevel
from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_permissions.mixins import (
    LoginOr403PermissionMixin,
    LoginOr404PermissionMixin,
)
from borrowd_permissions.models import BorrowdGroupOLP

from .filters import GroupFilter
from .forms import GroupCreateForm, GroupJoinForm, UpdateTrustLevelForm
from .models import BorrowdGroup, Membership, MembershipStatus

GroupInvite = namedtuple("GroupInvite", ["group_id", "group_name"])


def get_members_data(group: BorrowdGroup) -> list[dict[str, Any]]:
    """
    Helper function to format membership data for display.
    Returns a list of dicts with member information.
    """
    memberships = Membership.objects.filter(
        group=group, status=MembershipStatus.ACTIVE
    ).select_related("user")
    members_data = []
    for membership in memberships:
        members_data.append(
            {
                "user_id": membership.user.id,  # type: ignore
                "membership_id": membership.id,  # type: ignore
                "full_name": membership.user.profile.full_name(),  # type: ignore
                "profile_image": membership.user.profile.image,  # type: ignore
                "role": membership.is_moderator and "Moderator" or "Member",
            }
        )
    return members_data


class InviteSigner:
    """
    Static class to handle signing and unsigning of group invites.

    Uses Django's built-in signing library to create a timestamped
    signature of the group ID and name; this wrapper class just adds
    some default settings.

    Signing / encrypting / securely obfuscating invite links is in
    line with Borrowd's core value of Trust: since Groups should be
    hidden without explicit invitation, this approach prevents
    enumeration attacks on Group names and IDs.
    """

    _signer = TimestampSigner(sep="+")

    @staticmethod
    def sign_invite(group_id: int, group_name: str) -> str:
        return InviteSigner._signer.sign_object(obj=(group_id, group_name))

    @staticmethod
    def unsign_invite(signed: str, max_age: int = 60 * 60 * 24 * 7) -> GroupInvite:
        # expiry: int = settings.BORROWD_GROUP_INVITE_EXPIRY_SECONDS or max_age
        # decoded = InviteSigner._signer.unsign_object(signed, max_age=expiry)
        decoded = InviteSigner._signer.unsign_object(signed)
        return GroupInvite(*decoded)


class GroupCreateView(
    LoginRequiredMixin,  # type: ignore[misc]
    BorrowdTemplateFinderMixin,
    CreateView[BorrowdGroup, ModelForm[BorrowdGroup]],
):
    model = BorrowdGroup
    form_class = GroupCreateForm

    def form_valid(self, form: ModelForm[BorrowdGroup]) -> HttpResponse:
        if self.request.user.is_authenticated:
            form.instance.created_by_id = form.instance.updated_by_id = (  # type: ignore[attr-defined]
                self.request.user.pk
            )

        # This is a temporary property, only used in the post_save
        # signal to set the trust level between the group and the
        # user that created it.
        setattr(form.instance, "_temp_trust_level", form.cleaned_data["trust_level"])

        return super().form_valid(form)

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("borrowd_groups:group-list")
        return reverse("borrowd_groups:group-detail", args=[self.object.pk])


class GroupDeleteView(
    LoginOr404PermissionMixin,
    BorrowdTemplateFinderMixin,
    DeleteView[BorrowdGroup, ModelForm[BorrowdGroup]],
):
    # Todo: prevent non-admin/moderators from completing this action
    model = BorrowdGroup
    permission_required = BorrowdGroupOLP.DELETE
    success_url = reverse_lazy("borrowd_groups:group-list")


# No typing for django_guardian, so mypy doesn't like us subclassing.
class GroupDetailView(
    LoginOr403PermissionMixin,
    BorrowdTemplateFinderMixin,
    DetailView[BorrowdGroup],
):
    model = BorrowdGroup
    permission_required = BorrowdGroupOLP.VIEW

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        group: BorrowdGroup = self.object

        context["members_data"] = get_members_data(group)

        if self.request.user.is_authenticated:
            context["is_moderator"] = Membership.objects.filter(
                user=self.request.user,
                group=group,
                is_moderator=True,
                status=MembershipStatus.ACTIVE,
            ).exists()
            # Get the current user's membership to expose their trust level
            try:
                user_membership = Membership.objects.get(
                    user=self.request.user, group=group, status=MembershipStatus.ACTIVE
                )
                context["user_trust_level"] = user_membership.trust_level
            except Membership.DoesNotExist:
                context["user_trust_level"] = None

            # 255: Show pending members to moderators only
            if context["is_moderator"]:
                context["pending_members"] = Membership.objects.filter(
                    group=group, status=MembershipStatus.PENDING
                ).select_related("user")

        return context


class GroupInviteView(
    LoginOr404PermissionMixin,
    DetailView[BorrowdGroup],
):
    model = BorrowdGroup
    permission_required = BorrowdGroupOLP.VIEW
    template_name = "groups/group_invite.html"

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        group: BorrowdGroup = self.object
        encoded: str = InviteSigner.sign_invite(group.pk, group.name)
        context["join_url"] = self.request.build_absolute_uri(
            reverse("borrowd_groups:group-join", kwargs={"encoded": encoded})
        )
        return context


# No typing for django_guardian, so mypy doesn't like us subclassing.
class GroupJoinView(LoginRequiredMixin, View):  # type: ignore[misc]
    """
    View to handle group join requests via invite link.

    First validates the token in the invite link, redirecting to a
    descriptive error page if neccessary.

    On GET, displays basic information about the Group and a button
    to confirm joining.

    Then on POST, actions the joining of the user into the Group and
    displays a confirmation.
    """

    def _validate_invite(
        self, request: HttpRequest, encoded: str
    ) -> BorrowdGroup | HttpResponse:
        """
        Validates the invite token and returns either the relevant
        BorrowdGroup if validation passes, or an HttpResponse with
        the appropriate action if validation fails.
        """
        group_invite: GroupInvite
        err: str = ""

        try:
            group_invite = InviteSigner.unsign_invite(encoded)
        except SignatureExpired:
            err = "expired"
        except (TypeError, Exception):
            # Don't reveal any info about malformed tokens
            err = "invalid"

        if err:
            context = {"error_type": err}
            return render(request, "groups/group_join_error.html", context, status=400)

        # Check if the group exists
        # and if the name matches the ID
        group: BorrowdGroup
        try:
            # Why does mypy think `BorrowdGroup.objects.get` is
            # returning a `Group` and not a `BorrowdGroup`?
            group = BorrowdGroup.objects.get(
                pk=group_invite.group_id, name=group_invite.group_name
            )
        except (BorrowdGroup.DoesNotExist, ValueError):
            # Don't reveal any info about Group lookup
            err = "invalid"

        if err:
            context = {"error_type": err}
            return render(request, "groups/group_join_error.html", context, status=400)

        # Check if the user already has a membership record
        existing_membership = Membership.objects.filter(
            user=self.request.user, group=group
        ).first()
        if existing_membership:
            if existing_membership.status == MembershipStatus.PENDING:
                messages.info(
                    request, "Your request to join this group is pending approval."
                )
                return redirect("borrowd_groups:group-list")
            if existing_membership.status == MembershipStatus.ACTIVE:
                messages.info(request, "You are already a member of this group.")
                return redirect("borrowd_groups:group-detail", pk=group.pk)

            messages.error(
                request,
                f"You cannot join this group while membership is {existing_membership.status.lower()}.",
            )
            return redirect("borrowd_groups:group-list")

        return group

    def get(
        self, request: HttpRequest, encoded: str, *args: Any, **kwargs: str
    ) -> HttpResponse:
        val_res: BorrowdGroup | HttpResponse = self._validate_invite(request, encoded)
        if isinstance(val_res, HttpResponse):
            return val_res

        group: BorrowdGroup = val_res
        form = GroupJoinForm()

        context = {
            "object": group,
            "group": group,
            "form": form,
            "members_data": get_members_data(group),
        }
        return render(request, "groups/group_join.html", context)

    def post(
        self, request: HttpRequest, encoded: str, *args: Any, **kwargs: str
    ) -> HttpResponse:
        val_res: BorrowdGroup | HttpResponse = self._validate_invite(request, encoded)
        if isinstance(val_res, HttpResponse):
            return val_res

        group: BorrowdGroup = val_res

        form = GroupJoinForm(request.POST)
        # Making sure a Trust Level has been selected
        if not form.is_valid():
            context = {
                "object": group,
                "group": group,
                "form": form,
                "members_data": get_members_data(group),
            }
            return render(request, "groups/group_join.html", context)

        # Check if membership_requires_approval, set pending
        membership = group.add_user(  # type: ignore[arg-type]
            request.user, trust_level=form.cleaned_data["trust_level"]
        )
        if membership.status == MembershipStatus.PENDING:
            messages.info(request, "Your request is pending approval by a moderator.")
            return redirect("borrowd_groups:group-list")
        else:
            messages.success(request, f"Thanks for joining {group.name}!")

        # Redirect to the group detail page
        return redirect("borrowd_groups:group-detail", pk=group.pk)


# No typing for django_filter, so mypy doesn't like us subclassing.
class GroupListView(LoginRequiredMixin, FilterView):  # type: ignore[misc]
    template_name = "groups/group_list.html"
    model = Membership
    filterset_class = GroupFilter

    def get_template_names(self) -> list[str]:
        if self.request.headers.get("HX-Request"):
            return ["groups/group_list_card.html"]
        return [self.template_name]


class GroupUpdateView(
    LoginOr404PermissionMixin,
    BorrowdTemplateFinderMixin,
    UpdateView[BorrowdGroup, ModelForm[BorrowdGroup]],
):
    model = BorrowdGroup
    permission_required = BorrowdGroupOLP.EDIT
    fields = ["name", "description", "logo", "banner", "membership_requires_approval"]

    def form_valid(self, form: ModelForm[BorrowdGroup]) -> HttpResponse:
        if self.request.user.is_authenticated:
            form.instance.updated_by_id = self.request.user.pk  # type: ignore[attr-defined]
        return super().form_valid(form)

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("borrowd_groups:group-list")
        return reverse("borrowd_groups:group-detail", args=[self.object.pk])


class UpdateTrustLevelView(LoginRequiredMixin, View):  # type: ignore[misc]
    """
    View to handle updating a user's trust level for a group they're a member of.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        try:
            group = BorrowdGroup.objects.get(pk=pk)
        except BorrowdGroup.DoesNotExist:
            messages.error(request, "Group not found.")
            return redirect("borrowd_groups:group-list")  # type: ignore[return-value]

        try:
            membership = Membership.objects.get(user=request.user, group=group)
        except Membership.DoesNotExist:
            messages.error(request, "You are not a member of this group.")
            return redirect("borrowd_groups:group-detail", pk=pk)  # type: ignore[return-value]

        form = UpdateTrustLevelForm(request.POST)
        if form.is_valid():
            new_trust_level = form.cleaned_data["trust_level"]
            membership.trust_level = new_trust_level
            membership.save()
            # Get human-readable label for the trust level
            trust_level_label = dict(TrustLevel.choices)[int(new_trust_level)]
            messages.success(
                request, f"Your trust level has been updated to {trust_level_label}."
            )
        else:
            messages.error(request, "Invalid trust level selected.")

        return redirect("borrowd_groups:group-detail", pk=pk)  # type: ignore[return-value]


class RemoveMemberView(LoginRequiredMixin, View):  # type: ignore[misc]
    """
    View to handle removing a member from a group.
    Only moderators can remove members.
    """

    def post(self, request: HttpRequest, pk: int, user_id: int) -> HttpResponse:
        # Get the group
        try:
            group = BorrowdGroup.objects.get(pk=pk)
        except BorrowdGroup.DoesNotExist:
            messages.error(request, "Group not found.")
            return redirect("borrowd_groups:group-list")  # type: ignore[return-value]

        # Check if the requesting user is a moderator
        is_moderator = Membership.objects.filter(
            user=request.user, group=group, is_moderator=True
        ).exists()

        if not is_moderator:
            messages.error(request, "You do not have permission to remove members.")
            return redirect("borrowd_groups:group-detail", pk=pk)  # type: ignore[return-value]

        # Get the membership to remove
        try:
            membership = Membership.objects.get(user_id=user_id, group=group)
        except Membership.DoesNotExist:
            messages.error(request, "Member not found in this group.")
            return redirect("borrowd_groups:group-detail", pk=pk)  # type: ignore[return-value]

        # Prevent removing yourself
        if membership.user == request.user:
            messages.error(request, "You cannot remove yourself from the group.")
            return redirect("borrowd_groups:group-detail", pk=pk)  # type: ignore[return-value]

        # Remove the member
        member_name = membership.user.profile.full_name()  # type: ignore
        membership.delete()
        messages.success(request, f"{member_name} has been removed from the group.")

        return redirect("borrowd_groups:group-detail", pk=pk)  # type: ignore[return-value]


# 255: Handles approving pending members, which is just changing their status to active. Only moderators can approve.
class ApproveMemberView(LoginRequiredMixin, View):  # type: ignore[misc]
    def post(self, request: HttpRequest, membership_id: int) -> HttpResponse:
        membership = get_object_or_404(
            Membership, id=membership_id, status=MembershipStatus.PENDING
        )

        # Only moderators can approve
        if not Membership.objects.filter(
            user=request.user,
            group=membership.group,
            is_moderator=True,
            status=MembershipStatus.ACTIVE,
        ).exists():
            raise PermissionDenied

        membership.status = MembershipStatus.ACTIVE
        membership.save(update_fields=["status"])

        messages.success(
            request, f"{membership.user.profile.full_name()} has been approved."
        )
        return redirect("borrowd_groups:group-detail", pk=membership.group.pk)


#255:  handles denial of membership requests by moderator
class DenyMemberView(LoginRequiredMixin, View):  # type: ignore[misc]
    def post(self, request: HttpRequest, membership_id: int) -> HttpResponse:
        membership = get_object_or_404(
            Membership, id=membership_id, status=MembershipStatus.PENDING 
        ) # 404 if not found or not pending

        # Only moderators can deny
        if not Membership.objects.filter(
            user=request.user,
            group=membership.group,
            is_moderator=True,
            status=MembershipStatus.ACTIVE,
        ).exists():
            raise PermissionDenied

        membership.delete()
        messages.success(
            request, f"{membership.user.profile.full_name()} has been denied."
        )
        return redirect("borrowd_groups:group-detail", pk=membership.group.pk)
