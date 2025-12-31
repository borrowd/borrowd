from django.core.exceptions import PermissionDenied
from django.http import Http404
from guardian.mixins import PermissionRequiredMixin


class LoginOr404PermissionMixin(PermissionRequiredMixin):  # type: ignore[misc]
    """
    Anonymous users → redirect to login
    Authenticated users without permission → 404
    """

    def on_permission_check_fail(self, request, response, obj=None):  # type: ignore[no-untyped-def]
        user = self.request.user
        if not user.is_authenticated:
            return super().on_permission_check_fail(request, response, obj)
        raise Http404


class LoginOr403PermissionMixin(PermissionRequiredMixin):  # type: ignore[misc]
    """
    Anonymous users → redirect to login
    Authenticated users without permission → 403
    """

    def on_permission_check_fail(self, request, response, obj=None):  # type: ignore[no-untyped-def]
        user = self.request.user
        if not user.is_authenticated:
            return super().on_permission_check_fail(request, response, obj)
        raise PermissionDenied
