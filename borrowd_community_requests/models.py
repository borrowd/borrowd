from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import (
    CASCADE,
    PROTECT,
    CharField,
    DateTimeField,
    ForeignKey,
    Model,
    Q,
    QuerySet,
    TextField,
    UniqueConstraint,
)
from django.urls import reverse

from borrowd_groups.models import Membership, MembershipStatus
from borrowd_items.models import Item, ItemCategory
from borrowd_users.models import BorrowdUser

from .exceptions import CannotActOnOwnRequestException

MAX_ACTIVE_REQUESTS_PER_USER = 3


class CommunityRequestStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    CANCELLED = "CANCELLED", "Cancelled"
    FULFILLED = "FULFILLED", "Fulfilled"


class CommunityRequestQuerySet(QuerySet["CommunityRequest"]):
    def open(self) -> "CommunityRequestQuerySet":
        return self.filter(status=CommunityRequestStatus.OPEN)

    def visible_to(self, user: BorrowdUser) -> "CommunityRequestQuerySet":
        # Visibility follows shared active group membership.
        group_ids = Membership.objects.filter(
            user=user,
            status=MembershipStatus.ACTIVE,
        ).values_list("group_id", flat=True)

        requester_ids = Membership.objects.filter(
            group_id__in=group_ids,
            status=MembershipStatus.ACTIVE,
        ).values_list("user_id", flat=True)

        return (
            self.open()
            .filter(requester_id__in=requester_ids)
            .exclude(dismissals__user=user)
            .distinct()
            .order_by("-created_at")
        )

    def owned_by(self, user: BorrowdUser) -> "CommunityRequestQuerySet":
        return self.filter(requester=user).order_by("-created_at")


class CommunityRequest(Model):
    requester: ForeignKey[BorrowdUser] = ForeignKey(
        BorrowdUser,
        on_delete=CASCADE,
        related_name="community_requests",
    )
    category: ForeignKey[ItemCategory] = ForeignKey(
        ItemCategory,
        on_delete=PROTECT,
        related_name="community_requests",
    )
    item_name: CharField[str, str] = CharField(max_length=50)
    description: TextField[str, str] = TextField(max_length=500, blank=True)
    status: CharField[CommunityRequestStatus, str] = CharField(
        max_length=20,
        choices=CommunityRequestStatus.choices,
        default=CommunityRequestStatus.OPEN,
    )
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    objects = CommunityRequestQuerySet.as_manager()

    def __str__(self) -> str:
        return self.item_name

    def get_absolute_url(self) -> str:
        return reverse("community-request-list")

    def clean(self) -> None:
        super().clean()

        if self.requester_id is None:
            return

        if not Membership.objects.filter(
            user=self.requester,
            status=MembershipStatus.ACTIVE,
        ).exists():
            raise ValidationError(
                "You must belong to at least one group to create a community request."
            )

        active_requests = CommunityRequest.objects.filter(
            requester=self.requester,
            status=CommunityRequestStatus.OPEN,
        )

        if self.pk:
            active_requests = active_requests.exclude(pk=self.pk)

        if active_requests.count() >= MAX_ACTIVE_REQUESTS_PER_USER:
            raise ValidationError(
                f"You can only have {MAX_ACTIVE_REQUESTS_PER_USER} active community requests at a time."
            )

    def cancel(self) -> None:
        self.status = CommunityRequestStatus.CANCELLED
        self.save(update_fields=["status", "updated_at"])

    def mark_fulfilled(self) -> None:
        # Callable regardless of whether any CommunityRequestResponse rows
        # exist — the requester may have borrowed the item off-platform, or
        # from a response not tracked in-app, so no specific response needs
        # to be picked.
        self.status = CommunityRequestStatus.FULFILLED
        self.save(update_fields=["status", "updated_at"])

    def add_response(self, item: Item) -> "CommunityRequestResponse | None":
        if item.owner_id == self.requester_id:
            raise CannotActOnOwnRequestException("You can't fulfill your own request.")

        # The request stays OPEN so any number of lenders can respond —
        # locking the row only guards against a response racing a
        # concurrent close (cancel(), or a future mark_fulfilled()), not
        # against other responses. get_or_create() runs inside the same
        # lock/transaction so a lender accidentally double-submitting the
        # same item is idempotent rather than creating a duplicate row.
        #
        # select_for_update() is a no-op-with-warning on SQLite (used for
        # local/CI unit tests) but genuinely locks the row on PostgreSQL
        # (used by the CI Django-test job); the check-then-create inside the
        # same transaction is still race-safe either way, since every caller
        # re-reads the row fresh before deciding whether to write.
        with transaction.atomic():
            locked = CommunityRequest.objects.select_for_update().get(pk=self.pk)
            if locked.status != CommunityRequestStatus.OPEN:
                return None
            response, _ = CommunityRequestResponse.objects.get_or_create(
                request=self, item=item
            )
            return response

    def dismiss_for(self, user: BorrowdUser) -> None:
        if user.id == self.requester_id:
            raise CannotActOnOwnRequestException("You can't hide your own request.")

        CommunityRequestDismissal.objects.get_or_create(request=self, user=user)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            UniqueConstraint(
                fields=["requester", "item_name", "category"],
                condition=Q(status=CommunityRequestStatus.OPEN),
                name="unique_open_community_request_per_item",
            )
        ]


class CommunityRequestResponse(Model):
    """A lender's item offered in response to a community request. A
    request can have any number of responses — the PRD explicitly allows
    multiple lenders to respond to the same request."""

    request: ForeignKey[CommunityRequest] = ForeignKey(
        CommunityRequest,
        on_delete=CASCADE,
        related_name="responses",
    )
    item: ForeignKey[Item] = ForeignKey(
        Item,
        on_delete=CASCADE,
        related_name="community_request_responses",
    )
    created_at = DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.item} responds to {self.request}"


class CommunityRequestDismissal(Model):
    request: ForeignKey[CommunityRequest] = ForeignKey(
        CommunityRequest,
        on_delete=CASCADE,
        related_name="dismissals",
    )
    user: ForeignKey[BorrowdUser] = ForeignKey(
        BorrowdUser,
        on_delete=CASCADE,
        related_name="community_request_dismissals",
    )
    created_at = DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user} dismissed {self.request}"

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["request", "user"],
                name="unique_community_request_dismissal",
            )
        ]
