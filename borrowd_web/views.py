from django.http import HttpRequest, HttpResponse
from django.template import loader


def index(request: HttpRequest) -> HttpResponse:
    template = loader.get_template("web/index.html")
    return HttpResponse(template.render({}, request))
