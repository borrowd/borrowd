import base64
import json
import os
import sys
from urllib.parse import urlparse

from django.db.models import Model


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
def decode(variable: str):  # type: ignore
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
        if sys.version_info[1] > 5:
            return json.loads(base64.b64decode(variable))
        else:
            return json.loads(base64.b64decode(variable).decode("utf-8"))
    except json.decoder.JSONDecodeError as e:
        print("Error decoding JSON, code %d", json.decoder.JSONDecodeError)
        raise e


def get_platformsh_base_url() -> str | None:
    platform_routes = os.environ.get("PLATFORM_ROUTES")
    if not platform_routes:
        return None  # Not running on Platform.sh

    routes = json.loads(platform_routes)

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
