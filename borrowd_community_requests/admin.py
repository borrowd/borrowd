from typing import TYPE_CHECKING, TypeAlias

from django.contrib import admin

from .models import CommunityRequest, CommunityRequestDismissal

# ModelAdmin isn't generic at runtime, but mypy expects type parameters.
# Using a TYPE_CHECKING alias so Django and mypy are both happy.
if TYPE_CHECKING:
    CommunityRequestModelAdmin: TypeAlias = admin.ModelAdmin[CommunityRequest]
    CommunityRequestDismissalModelAdmin: TypeAlias = admin.ModelAdmin[
        CommunityRequestDismissal
    ]
else:
    CommunityRequestModelAdmin = admin.ModelAdmin
    CommunityRequestDismissalModelAdmin = admin.ModelAdmin


@admin.register(CommunityRequest)
class CommunityRequestAdmin(CommunityRequestModelAdmin):
    list_display = ("item_name", "category", "requester", "status", "created_at")
    list_filter = ("status", "category", "created_at")
    search_fields = ("item_name", "description", "requester__email")


@admin.register(CommunityRequestDismissal)
class CommunityRequestDismissalAdmin(CommunityRequestDismissalModelAdmin):
    list_display = ("request", "user", "created_at")
    search_fields = ("request__item_name", "user__email")
