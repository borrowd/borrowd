from django.http import HttpRequest

PWA_ICON_VERSION = "5"
PWA_LIGHT_COLOR = "#ffffff"
PWA_DARK_COLOR = "#0b0907"


def pwa_metadata(request: HttpRequest) -> dict[str, str]:
    return {
        "pwa_icon_version": PWA_ICON_VERSION,
        "pwa_light_color": PWA_LIGHT_COLOR,
        "pwa_dark_color": PWA_DARK_COLOR,
    }
