from ..base import *  # noqa: F403

DEBUG = True

STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405
DJANGO_VITE = {
    "default": {
        "dev_mode": DEBUG,
        "manifest_path": BASE_DIR / "build" / "manifest.json",  # noqa: F405
    }
}
