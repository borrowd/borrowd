from django.contrib import admin
from django.forms import ModelForm
from django.http import HttpRequest

from .models import BetaCode, BetaSignup


class BetaCodeAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    readonly_fields = ["code", "created_by", "updated_by", "created_at", "updated_at"]

    def save_model(
        self,
        request: HttpRequest,
        obj: BetaCode,
        form: ModelForm[BetaCode],
        change: bool,
    ) -> None:
        if not obj.pk:
            obj.created_by = request.user
            obj.code = BetaCode.generate_code()
        else:
            obj.updated_by = request.user
        obj.save()


class BetaSignupAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    # Make fields read-only
    readonly_fields = [field.name for field in BetaSignup._meta.fields]

    # Prevent adding and deleting
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: BetaSignup | None = None
    ) -> bool:
        return False


admin.site.register(BetaCode, BetaCodeAdmin)
admin.site.register(BetaSignup, BetaSignupAdmin)
