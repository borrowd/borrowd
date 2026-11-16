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
    # Keep these read-only so an item with an open request or loan
    # can't be marked available or deleted here.
    readonly_fields = ("status", "deleted_at", "deleted_by")

    def get_readonly_fields(
        self, request: HttpRequest, obj: Item | None = None
    ) -> list[str] | tuple[Any, ...]:
        fields = super().get_readonly_fields(request, obj)
        # The open transaction lists the current owner as its lender,
        # so don't allow an owner change until it is closed.
        if obj is not None and obj.get_current_transaction() is not None:
            return (*fields, "owner")
        return fields

    def save_model(
        self, request: HttpRequest, obj: Item, form: ModelForm[Item], change: bool
    ) -> None:
        with transaction.atomic():
            if not BorrowdUser.lock_account(obj.owner_id).is_active:
                raise PermissionDenied("An inactive account cannot own an item.")
            if not change:
                super().save_model(request, obj, form, change)
                return

            item = Item.lock_for_update(obj.pk)
            if item.deleted_at is not None:
                raise PermissionDenied("This item is no longer available.")
            # A request may have arrived after the form was rendered.
            if (
                "owner" in form.changed_data
                and item.get_current_transaction() is not None
            ):
                raise PermissionDenied(
                    "An item's owner cannot change while it has an open transaction."
                )
            # Save only edited fields so we don't overwrite other changes.
            changed_fields = set(form.changed_data)
            update_fields = {"updated_at"}
            for field in Item._meta.concrete_fields:
                if field.name in changed_fields:
                    setattr(item, field.attname, getattr(obj, field.attname))
                    update_fields.add(field.name)
            item.save(update_fields=update_fields)
            # Keep the form's item up to date for save_m2m().
            obj.refresh_from_db()


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
