from borrowd.config.env import env

from ..base import *  # noqa: F403

STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405

DJANGO_VITE = {
    "default": {
        "dev_mode": False,
        "manifest_path": BASE_DIR / "build" / "manifest.json",  # noqa: F405
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
