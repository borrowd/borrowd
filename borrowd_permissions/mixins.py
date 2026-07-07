from django.core.exceptions import PermissionDenied
from django.db.models import Model
from django.http import Http404, HttpRequest, HttpResponse
from guardian.mixins import PermissionRequiredMixin


class LoginOr404PermissionMixin(PermissionRequiredMixin):
    """
    Anonymous users → redirect to login
    Authenticated users without permission → 404
    """

    def on_permission_check_fail(
        self, request: HttpRequest, response: HttpResponse, obj: Model | None = None
    ) -> None:
        user = self.request.user
        if not user.is_authenticated:
            return super().on_permission_check_fail(request, response, obj)
        raise Http404


class LoginOr403PermissionMixin(PermissionRequiredMixin):
    """
    Anonymous users → redirect to login
    Authenticated users without permission → 403
    """

    def on_permission_check_fail(
        self, request: HttpRequest, response: HttpResponse, obj: Model | None = None
    ) -> None:
        user = self.request.user
        if not user.is_authenticated:
            return super().on_permission_check_fail(request, response, obj)
        raise PermissionDenied
