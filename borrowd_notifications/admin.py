from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import (
    Notification,
)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin[Notification]):
    list_display = [
        "notification_type",
        "recipient",
        "channels_display",
        "status",
        "is_read",
        "created_at",
        "sent_at",
        "related_object",
    ]
    list_filter = [
        "notification_type",
        "status",
        "is_read",
        "created_at",
        "sent_at",
    ]
    search_fields = [
        "recipient__email",
        "recipient__profile__first_name",
        "recipient__profile__last_name",
    ]
    readonly_fields = [
        "created_at",
        "sent_at",
        "related_object",
        "channels_display",
    ]
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Notification Details",
            {
                "fields": (
                    "notification_type",
                    "recipient",
                    "channels",
                    "status",
                    "is_read",
                )
            },
        ),
        (
            "Related Object",
            {
                "fields": ("content_type", "object_id"),
                "classes": ("collapse",),
            },
        ),
        (
            "Additional Data",
            {"fields": ("context_data", "error_message"), "classes": ("collapse",)},
        ),
        ("Timestamps", {"fields": ("created_at", "sent_at"), "classes": ("collapse",)}),
    )

    def channels_display(self, obj: Notification) -> str:
        """Display channels in a readable format."""
        if not obj.channels:
            return "No channels"
        return ", ".join(obj.channels)

    channels_display.short_description = "Channels"  # type: ignore[attr-defined]

    def related_object(self, obj: Notification) -> str:
        """Display the related object in a readable format."""
        if obj.content_object and obj.content_type:
            return f"{obj.content_type.model}: {obj.content_object}"  # type: ignore[attr-defined]
        return "No related object"

    related_object.short_description = "Related Object"  # type: ignore[attr-defined]

    def get_queryset(self, request: HttpRequest) -> "QuerySet[Notification]":
        """Optimize queryset with select_related for better performance."""
        return (
            super()
            .get_queryset(request)
            .select_related(
                "recipient",
                "recipient__profile",
                "content_type",
            )
        )
