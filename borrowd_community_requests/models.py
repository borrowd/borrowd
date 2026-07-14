from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import (
    CASCADE,
    PROTECT,
    SET_NULL,
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

MAX_ACTIVE_REQUESTS_PER_USER = 3


class CommunityRequestStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    CANCELLED = "CANCELLED", "Cancelled"


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
    fulfilled_by_item: ForeignKey[Item | None] = ForeignKey(
        Item,
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name="fulfilled_community_requests",
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

    def link_response_item(self, item: Item) -> bool:
        # Keep the request open so multiple lenders can respond.
        if self.fulfilled_by_item_id is not None:
            return False

        self.fulfilled_by_item = item
        self.save(update_fields=["fulfilled_by_item", "updated_at"])
        return True

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            UniqueConstraint(
                fields=["requester", "item_name", "category"],
                condition=Q(status=CommunityRequestStatus.OPEN),
                name="unique_open_community_request_per_item",
            )
        ]


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
