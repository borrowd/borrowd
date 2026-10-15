from django.contrib import admin
from django.http import HttpRequest

from .models import Item, ItemCategory, ItemPhoto, Transaction, TransactionStatusChange

admin.site.register([Item, ItemCategory, ItemPhoto])


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
