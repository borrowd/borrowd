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

    # PLATFORM_PROJECT_ENTROPY is unique to your project
    # Use it to define define Django's SECRET_KEY
    # See https://docs.djangoproject.com/en/5.2/ref/settings/#secret-key
    #
    # This should already be set correctly by the base config, but including this as insurance
    SECRET_KEY = env("PLATFORM_PROJECT_ENTROPY")

    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("PLATFORM_SMTP_HOST", default=None)
    EMAIL_PORT = 25
    DEFAULT_FROM_EMAIL = "noreply@borrowd.org"
    # Platform.sh proxies emails internally and encrypts before sending off-platform
    # TLS should be enabled whenever a 3rd-party SMTP service (e.g. SendGrid) is configured
    EMAIL_USE_TLS = False
    EMAIL_USE_SSL = False

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
#################################################################################

# Media storage
# Security considerations: https://docs.djangoproject.com/en/5.2/topics/security/#user-uploaded-content-security
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": "borrowd-media-prod-us-west-1",
            "default_acl": "public-read",
            "file_overwrite": False,
            "region_name": "us-west-1",
            "endpoint_url": "https://s3.us-west-1.wasabisys.com",
        },
    },
    # Vite would require some extra setup to use S3 for static files
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Redefine the static root based on the platform.sh directory
# See https://docs.djangoproject.com/en/5.2/ref/settings/#static-root
STATIC_ROOT = os.path.join(env("PLATFORM_APP_DIR"), "staticfiles")
DJANGO_VITE = {
    "default": {
        "dev_mode": False,
        "manifest_path": BASE_DIR / "build" / "manifest.json",  # noqa: F405
    }
}
