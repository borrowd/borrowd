import base64
import json
import os
import sys

from environ import ImproperlyConfigured

from ..base import *  # noqa: F403
from ..env import env

DEBUG = False

#################################################################################
# Platform.sh-specific configuration


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


# Import some platform.sh settings from the environment.
# The following block is only applied within platform.sh environments
# That is, only when this platform.sh variable is defined
if env("PLATFORM_APPLICATION_NAME") is not None:
    ALLOWED_HOSTS = [
        ".platformsh.site",
    ]

    # Redefine the static root based on the platform.sh directory
    # See https://docs.djangoproject.com/en/5.2/ref/settings/#static-root
    STATIC_ROOT = os.path.join(env("PLATFORM_APP_DIR"), "staticfiles")

    # PLATFORM_PROJECT_ENTROPY is unique to your project
    # Use it to define define Django's SECRET_KEY
    # See https://docs.djangoproject.com/en/5.2/ref/settings/#secret-key
    #
    # This should already be set correctly by the base config, but including this as insurance
    SECRET_KEY = env("PLATFORM_PROJECT_ENTROPY")

    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("PLATFORM_SMTP_HOST", default=None)
    EMAIL_PORT = 25
    EMAIL_USE_TLS = False
    EMAIL_USE_SSL = False
    DEFAULT_FROM_EMAIL = "noreply@borrowd.org"

    # This variable must always match the primary database relationship name, configured in .platform.app.yaml
    PLATFORMSH_DB_RELATIONSHIP = "db"

    # Database service configuration, POST-BUILD ONLY
    # As services aren't available during the build
    # (e.g. only available in deploy and later hooks)
    if (platform_env := env("PLATFORM_ENVIRONMENT", default=None)) is not None:
        platformRelationships = decode(env("PLATFORM_RELATIONSHIPS"))
        db_settings = platformRelationships[PLATFORMSH_DB_RELATIONSHIP][0]
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": db_settings["path"],
                "USER": db_settings["username"],
                "PASSWORD": db_settings["password"],
                "HOST": db_settings["host"],
                "PORT": db_settings["port"],
            },
        }
else:
    raise ImproperlyConfigured(
        "PLATFORM_APPLICATION_NAME is not set. This is not a platform.sh environment."
    )

# Media storage
# will need to add media storage settings for cloud provider
# e.g. using django-storages[google]
# Security considerations: https://docs.djangoproject.com/en/5.2/topics/security/#user-uploaded-content-security
# MEDIA_ROOT = ''
# MEDIA_URL = "https://storage.googleapis.com/<your-bucket-name>/media/"
# STORAGES = {
#     "default": {
#         "BACKEND": "storages.backends.gcloud.GoogleCloudStorage"
#     }
# }
