from django.core.exceptions import ValidationError
from django.db import models, transaction
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

from .exceptions import CannotActOnOwnRequestException

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

    # Scratch attribute stashed by borrowd_notifications' pre_save receiver so
    # its post_save counterpart can tell a genuine first fulfillment apart
    # from a later unrelated save (e.g. cancel()). Declared here (mirroring
    # Item._previous_status / Membership._previous_status) so mypy --strict
    # accepts the signal handler's assignment.
    _previous_fulfilled_by_item_id: int | None = None

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
        if item.owner_id == self.requester_id:
            raise CannotActOnOwnRequestException("You can't fulfill your own request.")

        # Keep the request open so multiple lenders can respond. Locking the
        # row (rather than a check-then-save on self) avoids a race between
        # two lenders linking an item to the same request at once: only the
        # first caller to lock the row and find fulfilled_by_item still null
        # wins, and the status==OPEN recheck races safely against cancel()
        # the same way — a request cancelled concurrently with a
        # fulfillment attempt can't be fulfilled after the fact.
        #
        # This re-fetches and saves through the ORM (rather than a plain
        # .filter().update()) so the write still goes through Model.save()
        # and fires pre_save/post_save signals — borrowd_notifications relies
        # on that to detect a genuine first fulfillment and send exactly one
        # COMMUNITY_REQUEST_FULFILLED notification.
        #
        # select_for_update() is a no-op-with-warning on SQLite (used for
        # local/CI unit tests) but genuinely locks the row on PostgreSQL
        # (used by the CI Django-test job); the check-then-save inside the
        # same transaction is still race-safe either way, since every caller
        # re-reads the row fresh before deciding whether to write.
        with transaction.atomic():
            locked = CommunityRequest.objects.select_for_update().get(pk=self.pk)
            if (
                locked.status != CommunityRequestStatus.OPEN
                or locked.fulfilled_by_item_id is not None
            ):
                return False
            locked.fulfilled_by_item = item
            locked.save(update_fields=["fulfilled_by_item", "updated_at"])

        self.fulfilled_by_item = item
        return True

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
