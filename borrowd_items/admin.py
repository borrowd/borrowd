from typing import Any

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms import ModelForm
from django.http import HttpRequest

from borrowd_users.models import BorrowdUser

from .models import Item, ItemCategory, ItemPhoto, Transaction, TransactionStatusChange


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin[Item]):
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


class TransactionStatusChangeInline(
    admin.TabularInline[TransactionStatusChange, Transaction]
):
    model = TransactionStatusChange
    extra = 0
    fields = (
        "changed_at",
        "from_status",
        "to_status",
        "action",
        "actor",
        "resolution_reason",
        "cancellation_reason",
        "backfilled",
    )
    readonly_fields = fields
    can_delete = False
    ordering = ("changed_at",)

    def has_add_permission(
        self, request: HttpRequest, obj: Transaction | None = None
    ) -> bool:
        return False


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin[Transaction]):
    list_display = ("id", "item", "party1", "party2", "status", "updated_at")
    list_filter = ("status",)
    inlines = (TransactionStatusChangeInline,)
