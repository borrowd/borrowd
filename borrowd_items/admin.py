from typing import Any

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest

from borrowd_users.models import BorrowdUser
from borrowd_users.request import get_authenticated_user

from .events import replay, skip
from .models import Item, ItemCategory, ItemPhoto, LifecycleEvent


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin[Item]):
    # Derived from the item's transaction; repair_item_statuses fixes drift.
    readonly_fields = ("status",)

    def get_readonly_fields(
        self, request: HttpRequest, obj: Item | None = None
    ) -> list[str] | tuple[Any, ...]:
        fields = super().get_readonly_fields(request, obj)
        # An open transaction names the owner as its lender.
        if obj is not None and obj.get_current_transaction() is not None:
            return (*fields, "owner")
        return fields

    def save_model(
        self, request: HttpRequest, obj: Item, form: ModelForm[Item], change: bool
    ) -> None:
        if change and "owner" not in form.changed_data:
            super().save_model(request, obj, form, change)
            return
        with transaction.atomic():
            # Account before Item. A closing account must not be handed an item.
            if not BorrowdUser.lock_account(obj.owner_id).is_active:
                raise PermissionDenied("An inactive account cannot own an item.")
            # A request may have arrived after the form was rendered.
            if (
                change
                and Item.lock_for_update(obj.pk).get_current_transaction() is not None
            ):
                raise PermissionDenied(
                    "An item's owner cannot change while it has an open transaction."
                )
            super().save_model(request, obj, form, change)


admin.site.register([ItemCategory, ItemPhoto])


class DeliveryFilter(admin.SimpleListFilter):
    title = "delivery"
    parameter_name = "delivery"

    def lookups(
        self, request: HttpRequest, model_admin: admin.ModelAdmin[Any]
    ) -> tuple[tuple[str, str], ...]:
        return (
            ("waiting", "Waiting"),
            ("parked", "Parked"),
            ("skipped", "Skipped"),
            ("delivered", "Delivered"),
        )

    def queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
        match self.value():
            case "waiting":
                return queryset.filter(
                    processed_at__isnull=True, failed_at__isnull=True
                )
            case "parked":
                return queryset.filter(
                    processed_at__isnull=True, failed_at__isnull=False
                )
            case "skipped":
                return queryset.exclude(skip_reason="")
            case "delivered":
                return queryset.filter(processed_at__isnull=False, skip_reason="")
        return queryset


@admin.register(LifecycleEvent)
class LifecycleEventAdmin(admin.ModelAdmin[LifecycleEvent]):
    list_display = ("occurred_at", "__str__", "action", "actor", "delivery", "attempts")
    list_filter = (DeliveryFilter,)
    ordering = ("-occurred_at",)
    actions = ("replay_events",)
    fields = (
        "id",
        "transaction",
        "item",
        "source_status",
        "target_status",
        "action",
        "actor",
        "revision",
        "command_key",
        "occurred_at",
        "attempts",
        "next_attempt_at",
        "processed_at",
        "failed_at",
        "last_error",
        "skipped_by",
        "skip_reason",
    )
    readonly_fields = tuple(field for field in fields if field != "skip_reason")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: LifecycleEvent | None = None
    ) -> bool:
        return False

    @admin.display(description="Delivery")
    def delivery(self, event: LifecycleEvent) -> str:
        if event.skip_reason:
            return "skipped"
        if event.processed_at is not None:
            return "delivered"
        return "parked" if event.failed_at is not None else "waiting"

    @admin.action(description="Replay the selected events")
    def replay_events(
        self, request: HttpRequest, queryset: QuerySet[LifecycleEvent]
    ) -> None:
        for event in queryset.filter(processed_at__isnull=True):
            replay(event)

    def save_model(
        self,
        request: HttpRequest,
        obj: LifecycleEvent,
        form: ModelForm[LifecycleEvent],
        change: bool,
    ) -> None:
        # Writing a skip reason is how an event gets skipped. Nothing else
        # here is editable.
        if "skip_reason" not in form.changed_data or obj.processed_at is not None:
            return
        if not obj.skip_reason.strip():
            self.message_user(request, "A skip needs a reason.", messages.ERROR)
            return
        skip(obj, by=get_authenticated_user(request), reason=obj.skip_reason)
