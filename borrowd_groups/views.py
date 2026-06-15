from collections import namedtuple
from typing import Any, cast
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.signing import SignatureExpired, TimestampSigner
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, DetailView, UpdateView, View
from django_filters.views import FilterView
from guardian.mixins import LoginRequiredMixin
from notifications.models import Notification

from borrowd.models import TrustLevel
from borrowd.util import BorrowdTemplateFinderMixin
from borrowd_items.models import Transaction, TransactionStatus
from borrowd_notifications.services import NotificationType
from borrowd_permissions.mixins import (
    LoginOr403PermissionMixin,
    LoginOr404PermissionMixin,
)
from borrowd_permissions.models import BorrowdGroupOLP
from borrowd_users.models import BorrowdUser, SearchTarget, SearchTerm

from .exceptions import ModeratorRequiredException
from .filters import GroupFilter
from .forms import (
    DUPLICATE_GROUP_NAME_ERROR,
    GroupCreateForm,
    GroupJoinForm,
    GroupUpdateForm,
    UpdateTrustLevelForm,
)
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


def _active_group_member_ids(group: BorrowdGroup) -> Any:
    """
    Return user IDs of ACTIVE members in the group.
    """
    return Membership.objects.filter(
        group=group,
        status=MembershipStatus.ACTIVE,
    ).values_list("user_id", flat=True)


def _users_share_another_active_group(
    user1: BorrowdUser,
    user2: BorrowdUser,
    excluding_group: BorrowdGroup,
) -> bool:
    """
    Return True if both users are ACTIVE members of another group
    besides the one currently being left.
    """
    user1_group_ids = (
        Membership.objects.filter(
            user=user1,
            status=MembershipStatus.ACTIVE,
        )
        .exclude(group=excluding_group)
        .values_list("group_id", flat=True)
    )

    return Membership.objects.filter(
        user=user2,
        status=MembershipStatus.ACTIVE,
        group_id__in=user1_group_ids,
    ).exists()


def _blocking_group_transactions_for_user(
    user: BorrowdUser,
    group: BorrowdGroup,
) -> QuerySet[Transaction]:
    """
    Return transactions that should block the user from leaving the group.

    A transaction blocks leaving only when:
    - it is in a borrowed state, and
    - both parties are active members of this group, and
    - the two parties do not remain connected through another active group.
    """
    active_member_ids = list(_active_group_member_ids(group))

    candidate_transactions = Transaction.objects.filter(
        Q(party1=user) | Q(party2=user),
        status__in=[
            TransactionStatus.COLLECTED,
            TransactionStatus.RETURN_ASSERTED,
        ],
        party1__in=active_member_ids,
        party2__in=active_member_ids,
    ).select_related("party1", "party2")

    blocking_transactions: list[Transaction] = []

    # ruff error fixed: F402 Import `transaction` from line 25 shadowed by loop variable

    for candidate_transaction in candidate_transactions:
        if candidate_transaction.party1 == user:
            other_party = cast(BorrowdUser, candidate_transaction.party2)
        else:
            other_party = cast(BorrowdUser, candidate_transaction.party1)

        if not _users_share_another_active_group(
            user1=user,
            user2=other_party,
            excluding_group=group,
        ):
            blocking_transactions.append(candidate_transaction)

    blocking_transaction_ids = [transaction.pk for transaction in blocking_transactions]

    return Transaction.objects.filter(pk__in=blocking_transaction_ids)


def user_has_active_transactions_in_group(
    user: BorrowdUser, group: BorrowdGroup
) -> bool:
    """
    Return True if the user is involved in any blocking transaction
    for the given group.
    """
    return _blocking_group_transactions_for_user(user, group).exists()


def user_has_active_borrows_in_group(user: BorrowdUser, group: BorrowdGroup) -> bool:
    """
    Return True if the user is currently the borrower (party2)
    in any blocking transaction for the given group.
    """
    return (
        _blocking_group_transactions_for_user(user, group).filter(party2=user).exists()
    )


def user_has_active_lends_in_group(user: BorrowdUser, group: BorrowdGroup) -> bool:
    """
    Return True if the user is currently the lender (party1)
    in any blocking transaction for the given group.
    """
    return (
        _blocking_group_transactions_for_user(user, group).filter(party1=user).exists()
    )


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
    CreateView[BorrowdGroup, GroupCreateForm],
):
    model = BorrowdGroup
    form_class = GroupCreateForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form: GroupCreateForm) -> HttpResponse:
        if self.request.user.is_authenticated:
            form.instance.created_by_id = form.instance.updated_by_id = (  # type: ignore[attr-defined]
                self.request.user.pk
            )

        # This is a temporary property, only used in the post_save
        # signal to set the trust level between the group and the
        # user that created it.
        setattr(form.instance, "_temp_trust_level", form.cleaned_data["trust_level"])

        return super().form_valid(form)

    def form_invalid(self, form: GroupCreateForm) -> HttpResponse:
        name_errors: list[str] = [str(error) for error in form.errors.get("name", [])]
        if DUPLICATE_GROUP_NAME_ERROR in name_errors:
            messages.error(self.request, DUPLICATE_GROUP_NAME_ERROR)

        return super().form_invalid(form)

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("borrowd_groups:group-list")
        return reverse("borrowd_groups:group-detail", args=[self.object.pk])


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
            user: BorrowdUser = self.request.user  # type: ignore[assignment]

            context["is_moderator"] = Membership.objects.filter(
                user=user,
                group=group,
                is_moderator=True,
                status=MembershipStatus.ACTIVE,
            ).exists()
            # Get the current user's membership to expose their trust level
            try:
                user_membership = Membership.objects.get(
                    user=user, group=group, status=MembershipStatus.ACTIVE
                )
                context["user_trust_level"] = user_membership.trust_level
            except Membership.DoesNotExist:
                context["user_trust_level"] = None

            # Flags used to decide which leave-group modal to open.
            if context["user_trust_level"] is not None:
                context["show_leave_group_button"] = True
                context["leave_group_is_moderator"] = context["is_moderator"]
                context["leave_group_has_active_borrows"] = (
                    user_has_active_borrows_in_group(user, group)
                )
                context["leave_group_has_active_lends"] = (
                    user_has_active_lends_in_group(user, group)
                )
                context["leave_group_requires_approval_to_rejoin"] = (
                    group.membership_requires_approval
                )
            else:
                context["show_leave_group_button"] = False
                context["leave_group_is_moderator"] = False
                context["leave_group_has_active_borrows"] = False
                context["leave_group_has_active_lends"] = False
                context["leave_group_requires_approval_to_rejoin"] = False

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

    def dispatch(
        self, request: HttpRequest, encoded: str, *args: Any, **kwargs: str
    ) -> HttpResponseBase:
        if not request.user.is_authenticated:
            join_path = request.get_full_path()
            request.session["post_onboarding_redirect"] = join_path

            login_url = reverse("account_login")
            query = urlencode({"next": join_path})
            return redirect(f"{login_url}?{query}")

        return super().dispatch(request, encoded=encoded, *args, **kwargs)

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
                messages.warning(request, "Your request is still pending.")
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
        membership = group.add_user(
            request.user,  # type: ignore[arg-type]
            trust_level=form.cleaned_data["trust_level"],
        )
        if membership.status == MembershipStatus.PENDING:
            messages.info(request, "Your request is pending approval by a moderator.")
            return redirect("borrowd_groups:group-list")
        else:
            messages.success(request, f"Thanks for joining {group.name}!")

        # Redirect to the group detail page
        return redirect("borrowd_groups:group-detail", pk=group.pk)


def get_memberships_with_pending_actions(memberships: list[Membership]) -> set[int]:
    """
    Given a list of Membership objects, returns the set of group IDs for which
    the membership is held by a moderator and there are pending membership
    approval requests.

    Only groups where the user is a moderator are considered, and only groups
    that actually have at least one PENDING membership are returned.
    """
    moderator_group_ids = [m.group_id for m in memberships if m.is_moderator]  # type: ignore[attr-defined]
    if not moderator_group_ids:
        return set()
    return set(
        Membership.objects.filter(
            group_id__in=moderator_group_ids,
            status=MembershipStatus.PENDING,
        ).values_list("group_id", flat=True)
    )


# No typing for django_filter, so mypy doesn't like us subclassing.
class GroupListView(LoginRequiredMixin, FilterView):  # type: ignore[misc]
    template_name = "groups/group_list.html"
    model = Membership
    filterset_class = GroupFilter

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        term = request.GET.get("search")
        if term is not None:
            user: BorrowdUser = request.user  # type: ignore[assignment]
            SearchTerm.record_search(
                user=user,
                target=SearchTarget.GROUPS,
                term=term,
            )
        return super().get(request, *args, **kwargs)  # type: ignore[no-any-return]

    def get_template_names(self) -> list[str]:
        if self.request.headers.get("HX-Request"):
            return ["groups/group_list_card.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs: str) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)

        memberships = list(context.get("object_list", []))
        pending_action_group_ids = get_memberships_with_pending_actions(memberships)

        for membership in memberships:
            setattr(
                membership,
                "has_pending_actions",
                membership.is_moderator
                and membership.group_id in pending_action_group_ids,
            )

        context["object_list"] = memberships
        context["has_groups"] = Membership.objects.filter(
            user=self.request.user
        ).exists()
        return context


class GroupUpdateView(
    LoginOr404PermissionMixin,
    BorrowdTemplateFinderMixin,
    UpdateView[BorrowdGroup, GroupUpdateForm],
):
    model = BorrowdGroup
    permission_required = BorrowdGroupOLP.EDIT
    form_class = GroupUpdateForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form: GroupUpdateForm) -> HttpResponse:
        if self.request.user.is_authenticated:
            form.instance.updated_by_id = self.request.user.pk  # type: ignore[attr-defined]
        return super().form_valid(form)

    def form_invalid(self, form: GroupUpdateForm) -> HttpResponse:
        name_errors: list[str] = [str(error) for error in form.errors.get("name", [])]
        if DUPLICATE_GROUP_NAME_ERROR in name_errors:
            messages.error(self.request, DUPLICATE_GROUP_NAME_ERROR)

        return super().form_invalid(form)

    def get_success_url(self) -> str:
        if self.object is None:
            return reverse("borrowd_groups:group-list")
        return reverse("borrowd_groups:group-detail", args=[self.object.pk])


class UpdateTrustLevelView(LoginRequiredMixin, View):  # type: ignore[misc]
    """
    View to handle updating a user's trust level for a group they're a member of.
    """

    def post(
        self, request: HttpRequest, pk: int
    ) -> HttpResponsePermanentRedirect | HttpResponseRedirect:
        try:
            group = BorrowdGroup.objects.get(pk=pk)
        except BorrowdGroup.DoesNotExist:
            messages.error(request, "Group not found.")
            return redirect("borrowd_groups:group-list")

        try:
            membership = Membership.objects.get(user=request.user, group=group)
        except Membership.DoesNotExist:
            messages.error(request, "You are not a member of this group.")
            return redirect("borrowd_groups:group-detail", pk=pk)

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

        return redirect("borrowd_groups:group-detail", pk=pk)


class RemoveMemberView(LoginRequiredMixin, View):  # type: ignore[misc]
    """
    View to handle removing a member from a group.
    Only moderators can remove members.
    """

    def post(
        self, request: HttpRequest, pk: int, user_id: int
    ) -> HttpResponsePermanentRedirect | HttpResponseRedirect:
        # Get the group
        try:
            group = BorrowdGroup.objects.get(pk=pk)
        except BorrowdGroup.DoesNotExist:
            messages.error(request, "Group not found.")
            return redirect("borrowd_groups:group-list")

        # Check if the requesting user is a moderator
        is_moderator = Membership.objects.filter(
            user=request.user, group=group, is_moderator=True
        ).exists()

        if not is_moderator:
            messages.error(request, "You do not have permission to remove members.")
            return redirect("borrowd_groups:group-detail", pk=pk)

        # Get the membership to remove
        try:
            membership = Membership.objects.get(user_id=user_id, group=group)
        except Membership.DoesNotExist:
            messages.error(request, "Member not found in this group.")
            return redirect("borrowd_groups:group-detail", pk=pk)

        # Prevent removing yourself
        if membership.user == request.user:
            messages.error(request, "You cannot remove yourself from the group.")
            return redirect("borrowd_groups:group-detail", pk=pk)

        # Remove the member using the model method, which also removes the
        # user from the underlying Django auth Group (perms_group), revoking
        # their inherited object-level permissions on other members' items.
        member_name = membership.user.profile.full_name()  # type: ignore
        try:
            group.remove_user(membership.user)  # type: ignore[arg-type]
        except ModeratorRequiredException:
            messages.error(
                request,
                f"Cannot remove {member_name}: they are the last moderator of this group.",
            )
            return redirect("borrowd_groups:group-detail", pk=pk)
        messages.success(request, f"{member_name} has been removed from the group.")

        return redirect("borrowd_groups:group-detail", pk=pk)


# 255: Handles approving pending members, which is just changing their status to active. Only moderators can approve.
class ApproveMemberView(LoginRequiredMixin, View):  # type: ignore[misc]
    def post(
        self, request: HttpRequest, membership_id: int
    ) -> HttpResponsePermanentRedirect | HttpResponseRedirect:
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

        messages.success(request, "Request approved.")
        return redirect("borrowd_groups:group-detail", pk=membership.group.pk)  # type: ignore[attr-defined]


# 255:  handles denial of membership requests by moderator
class DenyMemberView(LoginRequiredMixin, View):  # type: ignore[misc]
    def post(
        self, request: HttpRequest, membership_id: int
    ) -> HttpResponsePermanentRedirect | HttpResponseRedirect:
        membership = get_object_or_404(
            Membership, id=membership_id, status=MembershipStatus.PENDING
        )  # 404 if not found or not pending

        # Only moderators can deny
        if not Membership.objects.filter(
            user=request.user,
            group=membership.group,
            is_moderator=True,
            status=MembershipStatus.ACTIVE,
        ).exists():
            raise PermissionDenied

        membership.delete()
        messages.info(request, "Request denied.")
        return redirect("borrowd_groups:group-detail", pk=membership.group.pk)  # type: ignore[attr-defined]


class LeaveGroupView(LoginRequiredMixin, View):  # type: ignore[misc]
    """
    Allow a group member to leave a group.
    Currently, users with active transactions cannot leave.
    """

    def post(
        self, request: HttpRequest, pk: int
    ) -> HttpResponsePermanentRedirect | HttpResponseRedirect:
        group = get_object_or_404(BorrowdGroup, pk=pk)
        user: BorrowdUser = request.user  # type: ignore[assignment]

        membership = Membership.objects.filter(
            user=user,
            group=group,
            status=MembershipStatus.ACTIVE,
        ).first()

        if membership is None:
            messages.error(request, "You are not a member of this group.")
            return redirect("borrowd_groups:group-detail", pk=pk)

        # Members with blocking borrowed-item transactions must stay in
        # the group until those transactions are resolved.
        if user_has_active_transactions_in_group(user, group):
            messages.error(
                request,
                "You must first confirm the return of any borrowed items before leaving this group.",
            )
            return redirect("borrowd_groups:group-detail", pk=pk)

        # Allow moderators to leave through this flow, even if they are the
        # last moderator. Groups without moderators are allowed for now; later
        # iterations will handle moderator handoff and member notifications.
        group.remove_user(user, bypass_last_moderator_check=True)

        # If the group no longer has any active members, delete it.
        # This is a temporary fallback until archive / soft-delete exists.
        remaining_active_members = Membership.objects.filter(
            group=group,
            status=MembershipStatus.ACTIVE,
        ).exists()

        if not remaining_active_members:
            group.delete()

        messages.success(request, f"You left {group.name}.")
        return redirect("borrowd_groups:group-list")


class BecomeModeratorView(LoginRequiredMixin, View):  # type: ignore[misc]
    """
    Allow first active member to claim moderator role.
    """

    def post(
        self, request: HttpRequest, pk: int
    ) -> HttpResponsePermanentRedirect | HttpResponseRedirect:
        user: BorrowdUser = request.user  # type: ignore[assignment]

        with transaction.atomic():
            # Lock group row. This prevents race condition (two users clicking)
            group = get_object_or_404(BorrowdGroup.objects.select_for_update(), pk=pk)

            membership = get_object_or_404(
                Membership,
                user=user,
                group=group,
                status=MembershipStatus.ACTIVE,
            )

            # If someone already became moderator -> exit
            already_has_moderator = Membership.objects.filter(
                group=group,
                is_moderator=True,
                status=MembershipStatus.ACTIVE,
            ).exists()

            if already_has_moderator or not group.needs_moderator:
                messages.info(request, "This group already has a moderator.")
                return redirect("borrowd_groups:group-detail", pk=group.pk)

            # Assign moderator
            membership.is_moderator = True
            membership.save(update_fields=["is_moderator"])

            # Clear notifications for ALL users
            group_content_type = ContentType.objects.get_for_model(BorrowdGroup)

            Notification.objects.filter(
                verb=NotificationType.GROUP_NEEDS_MODERATOR.value,
                target_content_type=group_content_type,
                target_object_id=group.pk,
            ).update(unread=False)

        messages.success(request, "You’re now a moderator")
        return redirect("borrowd_groups:group-detail", pk=group.pk)
