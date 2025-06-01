from ..base import *  # noqa: F403

DEBUG = True
STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405

DJANGO_VITE = {
    "default": {
        "dev_mode": True,
        "manifest_path": BASE_DIR / "assets" / "manifest.json",  # noqa: F405
    }
}
