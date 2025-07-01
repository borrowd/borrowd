from ..base import *  # noqa: F403
from ..base import BASE_DIR, INSTALLED_APPS  # explicitly import what we need

DEBUG = True

STATIC_ROOT = BASE_DIR / "staticfiles"
DJANGO_VITE = {
    "default": {
        "dev_mode": DEBUG,
        "manifest_path": BASE_DIR / "build" / "manifest.json",  # noqa: F405
    }
}

# Insert django_vite in second-to-last position of INSTALLED_APPS
INSTALLED_APPS = INSTALLED_APPS[:-1] + ["django_vite"] + INSTALLED_APPS[-1:]
