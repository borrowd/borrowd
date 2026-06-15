import base64
import json
import logging
import os
from typing import Any
from urllib.parse import urlparse

from django.db.models import Model
from django.http import HttpRequest
from django.urls import Resolver404, resolve

logger = logging.getLogger(__name__)


def _is_safe_back_url(url: str, request: HttpRequest) -> bool:
    """
    True if `url` is safe to use as a back-button target: a relative path,
    or an absolute URL whose host matches the current request's host.
    Blocks open-redirect targets (`https://evil.example/...`),
    protocol-relative URLs (`//evil.example/...`), and dangerous schemes
    (`javascript:`, `data:`, etc.).

    I debated using Django's `url_has_allowed_host_and_scheme` rather than this
    custom function. However, I opted for this at the momnet as `url_has_allowed_host_and_scheme`
    is a private function for 5.2, and the following forum post put me off a bit.
    https://forum.djangoproject.com/t/why-is-the-use-of-url-has-allowed-host-and-scheme-discouraged/35314
    Why validate at all: https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html
    """

    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return False
    if parsed.netloc and parsed.netloc != request.get_host():
        return False
    return True


# https://peps.python.org/pep-3102/
def resolve_back_url(
    request: HttpRequest,
    *,
    fallback_url: str,
    allowed_url_names: set[str],
) -> str:
    """
    Pick a back-button target for any page that wants a smart back arrow.

    Resolution order:

    1. `?next=` query param. Explicit override -- when a caller knows
       where the user should go next, it attaches `?next=<url>`
       and we honor it if it passes the same-origin check.
    2. HTTP Referer header. Same-origin, on `allowed_url_names`,
       and not the page we're already on. Query string is preserved so filtered
       lists keep filters.
       https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Referer
    3. `fallback_url`. Caller-supplied default for direct nav or a referer we didn't trust.

    See:
    https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html#allowlist-vs-denylist
    """

    """
    Using `url_has_allowed_host_and_scheme` instead of `_is_safe_back_url`
    would look something like:
    ```
    next_url = request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    ```
    """
    next_url = request.GET.get("next")
    if next_url and _is_safe_back_url(next_url, request):
        return next_url

    referer = request.META.get("HTTP_REFERER")
    if referer:
        parsed = urlparse(referer)
        # Same-origin check: empty netloc means relative (same host
        # implicitly); otherwise host must match ours exactly.
        # Wondering "wtf is netloc?"? see: https://docs.python.org/3/library/urllib.parse.html
        if parsed.netloc in ("", request.get_host()):
            # Skip Referers pointing at the page we're already on.
            # Unless you'd like to just have the user click the back button
            # more and more as they fall deeper and deeper into frustration
            if parsed.path != request.path:
                try:
                    # resolve() maps a URL path to its Django route so we
                    # can check the URL name against the allowlist.
                    # https://docs.djangoproject.com/en/5.2/ref/urlresolvers/#resolve
                    match = resolve(parsed.path)
                except Resolver404:
                    # Path isn't one of our routes. Maybe it's a static asset,
                    # a third party url , a url that doens't match a view, etc.
                    # Therefore, fall through to the fallback_url.
                    pass
                else:
                    # else the path resolved successfully, so check the URL name against the allowlist.
                    if match.url_name in allowed_url_names:
                        suffix = f"?{parsed.query}" if parsed.query else ""
                        return f"{parsed.path}{suffix}"
    return fallback_url


class BorrowdTemplateFinderMixin:
    """
    Mixin to find the template for generic class-based views. Removes
    'borrowd_' prefix from our app names.

    Background:
    ---------------
    Django's generic class-based views save a lot of boilerplate code.
    One of the ways they do that is to make assumptions about certain
    configuration - all very overridable. One of those assumptions is
    that the template is found under a directory named after the app,
    and a file named after the model. This is a good convention, but
    it doesn't work for us because we prefix our app names with
    'borrowd_' to avoid collisions with other apps. This mixin removes
    the 'borrowd_' prefix from the app name when looking for the
    template. It's a very simply thing to do, but we've put it in a
    mixin so that we can use it generically across all of our apps.
    """

    model: type[Model]
    template_name_suffix: str

    def get_template_names(self) -> list[str]:
        app_name = self.model._meta.app_label.replace("borrowd_", "")
        model_name = self.model.__name__.lower().replace("borrowd", "")
        return [f"{app_name}/{model_name}{self.template_name_suffix}.html"]


# Helper function for decoding base64-encoded JSON variables.
# There is a platform.sh helper package for reading config variables: https://github.com/platformsh/config-reader-python
# but not sure it is worth adding another dependency at this point.
def decode(variable: str) -> Any:
    """Decodes a Platform.sh environment variable.
    Args:
        variable (string):
            Base64-encoded JSON (the content of an environment variable).
    Returns:
        An dict (if representing a JSON object), or a scalar type.
    Raises:
        JSON decoding error.
    """
    try:
        return json.loads(base64.b64decode(variable))
    except json.decoder.JSONDecodeError as e:
        print("Error decoding JSON, code %d", json.decoder.JSONDecodeError)
        raise e


def get_platformsh_base_url() -> str | None:
    platform_routes = os.environ.get("PLATFORM_ROUTES")
    if not platform_routes:
        return None  # Not running on Platform.sh

    routes = decode(platform_routes)

    # Choose the primary HTTPS route (without `-internal`)
    https_routes = [
        url
        for url in routes.keys()
        if url.startswith("https://") and "-internal" not in url
    ]
    if not https_routes:
        return None

    # If multiple, sort to prefer bare domain (or do your own logic)
    primary_url = sorted(https_routes)[0]
    parsed = urlparse(primary_url)
    return f"{parsed.scheme}://{parsed.netloc}"
