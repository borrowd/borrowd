from collections import namedtuple
from typing import Any

# from django.conf import settings
from django.contrib import messages
from django.core.signing import SignatureExpired, TimestampSigner
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.template import loader as template_loader
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    UpdateView,
    View,
)
from django_filters.views import FilterView
from guardian.mixins import LoginRequiredMixin, PermissionRequiredMixin

from borrowd.util import BorrowdTemplateFinderMixin

from .filters import GroupFilter
from .forms import GroupCreateForm, GroupJoinForm
from .models import BorrowdGroup, Membership

GroupInvite = namedtuple("GroupInvite", ["group_id", "group_name"])


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
    BorrowdTemplateFinderMixin, CreateView[BorrowdGroup, ModelForm[BorrowdGroup]]
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
    BorrowdTemplateFinderMixin, DeleteView[BorrowdGroup, ModelForm[BorrowdGroup]]
):
    # Todo: prevent non-admin/moderators from completing this action
    model = BorrowdGroup
    success_url = reverse_lazy("borrowd_groups:group-list")


# No typing for django_guardian, so mypy doesn't like us subclassing.
class GroupDetailView(
    LoginRequiredMixin,  # type: ignore[misc]
    PermissionRequiredMixin,  # type: ignore[misc]
    BorrowdTemplateFinderMixin,
    DetailView[BorrowdGroup],
):
    model = BorrowdGroup
    permission_required = "view_this_group"
    return_403 = True

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        group: BorrowdGroup = self.object

        memberships = Membership.objects.filter(group=group).select_related("user")

        members_data = []
        for membership in memberships:
            members_data.append(
                {
                    "full_name": membership.user.profile.full_name(),  # type: ignore
                    "profile_image": membership.user.profile.image,  # type: ignore
                    "role": membership.is_moderator and "Moderator" or "Member",
                }
            )

        context["members_data"] = members_data
        if self.request.user.is_authenticated:
            context["is_moderator"] = Membership.objects.filter(
                user=self.request.user, group=group, is_moderator=True
            ).exists()
        return context


# TODO: secure to Group members (not just logged-in users)
class GroupInviteView(DetailView[BorrowdGroup]):
    model = BorrowdGroup
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

        # Check if the user is already a member
        if Membership.objects.filter(user=self.request.user, group=group).exists():
            messages.info(request, "You are already a member of this group.")
            return redirect("borrowd_groups:group-detail", pk=group.pk)

        return group

    def get(
        self, request: HttpRequest, encoded: str, *args: Any, **kwargs: str
    ) -> HttpResponse:
        val_res: BorrowdGroup | HttpResponse = self._validate_invite(request, encoded)
        if isinstance(val_res, HttpResponse):
            return val_res

        form = GroupJoinForm()

        context = {"object": val_res, "group": val_res, "form": form}
        return render(request, "groups/group_join.html", context)

    def post(
        self, request: HttpRequest, encoded: str, *args: Any, **kwargs: str
    ) -> HttpResponse:
        val_res: BorrowdGroup | HttpResponse = self._validate_invite(request, encoded)
        if isinstance(val_res, HttpResponse):
            return val_res

        # Just rename the var to avoid confusion
        group: BorrowdGroup = val_res

        form = GroupJoinForm(request.POST)
        # Making sure a Trust Level has been selected
        if not form.is_valid():
            return render(request, "groups/group_join.html", {"form": form})

        # Wonder what we can do to cast request.user to our
        # custom user model, so mypy doesn't complain here?
        group.add_user(request.user, trust_level=form.cleaned_data["trust_level"])  # type: ignore[arg-type]

        messages.success(request, f"Thanks for joining {group.name}!")
        # Redirect to the group detail page
        return redirect("borrowd_groups:group-detail", pk=group.pk)


# No typing for django_filter, so mypy doesn't like us subclassing.
class GroupListView(FilterView):  # type: ignore[misc]
    template_name = "groups/group_list.html"
    model = Membership
    filterset_class = GroupFilter


class GroupUpdateView(
    BorrowdTemplateFinderMixin, UpdateView[BorrowdGroup, ModelForm[BorrowdGroup]]
):
    model = BorrowdGroup
    fields = ["name", "description", "logo", "banner", "membership_requires_approval"]

    def form_valid(self, form: ModelForm[BorrowdGroup]) -> HttpResponse:
        if self.request.user.is_authenticated:
            form.instance.updated_by_id = self.request.user.pk  # type: ignore[attr-defined]
        return super().form_valid(form)

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("borrowd_groups:group-list")
        return reverse("borrowd_groups:group-detail", args=[self.object.pk])


def forbidden(request: HttpRequest) -> HttpResponse:
    template = template_loader.get_template("./templates/403.html")
    body = template.render
    return HttpResponse(body, status=403)
