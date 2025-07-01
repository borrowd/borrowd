from ..base import BASE_DIR  # explicitly import what we need

DEBUG = True

STATIC_ROOT = BASE_DIR / "staticfiles"
DJANGO_VITE = {
    "default": {
        "dev_mode": DEBUG,
        "manifest_path": BASE_DIR / "build" / "manifest.json",  # noqa: F405
    }
}
