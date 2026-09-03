from typing import Any, TypeVar

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Model, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.views.generic.detail import SingleObjectMixin
from guardian.mixins import PermissionRequiredMixin

_ObjectT = TypeVar("_ObjectT", bound=Model)


class CachedObjectMixin(SingleObjectMixin[_ObjectT]):
    """Reuse the object already loaded for an object-permission check."""

    object: _ObjectT

    def get_object(
        self,
        queryset: QuerySet[_ObjectT] | None = None,
    ) -> _ObjectT:
        if hasattr(self, "object"):
            return self.object
        self.object = super().get_object(queryset)
        return self.object


class _LoginRequiredPermissionMixin(PermissionRequiredMixin):
    """Handle anonymous requests before object-level permission checks."""

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        if not request.user.is_authenticated:
            login_response = redirect_to_login(
                request.get_full_path(),
                login_url=self.login_url,
                redirect_field_name=self.redirect_field_name,
            )
            if request.headers.get("HX-Request") == "true":
                # A normal 302 stays inside htmx's request. HX-Redirect moves
                # the whole browser to login instead of swapping login HTML.
                # https://htmx.org/headers/hx-redirect/
                return HttpResponse(headers={"HX-Redirect": login_response["Location"]})
            return login_response
        # django-guardian's dispatch method has no type annotations.
        response: HttpResponseBase = super().dispatch(  # type: ignore[no-untyped-call]
            request, *args, **kwargs
        )
        return response


class LoginOr404PermissionMixin(_LoginRequiredPermissionMixin):
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


class LoginOr403PermissionMixin(_LoginRequiredPermissionMixin):
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
