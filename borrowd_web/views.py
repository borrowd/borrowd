from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from django.template import loader


def favicon(request: HttpRequest) -> HttpResponse:
    file = (settings.BASE_DIR / "static" / "favicon.ico").open("rb")
    return FileResponse(file, content_type="image/x-icon")

def index(request: HttpRequest) -> HttpResponse:
    template = loader.get_template("landing/index.html")
    return HttpResponse(template.render({}, request))
