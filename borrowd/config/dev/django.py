# for some unknown reason, pre-commit cannot find sentry_sdk
import sentry_sdk  # type: ignore[import-not-found]

from borrowd.config.env import env

from ..base import *  # noqa: F403

if env("DEBUG", cast=str, default="true").lower() in ("1", "t", "true", "yes", "y"):
    DEBUG = True
else:
    print("running server with DEBUG mode OFF")
    DEBUG = False
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405
DJANGO_VITE = {
    "default": {
        "dev_mode": DEBUG,
        "manifest_path": BASE_DIR / "build" / "manifest.json",  # noqa: F405
    }
}

if env.bool("LOCAL_SENTRY_ENABLED", default=False):
    sentry_sdk.init(
        dsn=SENTRY_DSN,  # noqa: F405
        send_default_pii=True,
        environment="local",
    )
