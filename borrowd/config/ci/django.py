from borrowd.config.env import env

from ..base import *

STATIC_ROOT = BASE_DIR / "staticfiles"

DJANGO_VITE = {
    "default": {
        "dev_mode": False,
        "manifest_path": BASE_DIR / "build" / "manifest.json",
    }
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", default="borrowd"),
        "USER": env("DB_USER", default="borrowd"),
        "PASSWORD": env("DB_PASSWORD", default="borrowd"),
        "HOST": env("DB_HOST", default="127.0.0.1"),
        "PORT": env("DB_PORT", default="5432"),
    }
}

# Lets CI boot a live server for the E2E suite: with DEBUG on, runserver also
# serves static and media files, and the loopback hosts are accepted.
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
