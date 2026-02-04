from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from django.template import loader
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


def favicon(request: HttpRequest) -> FileResponse:
    file = (settings.BASE_DIR / "static" / "favicon.ico").open("rb")
    return FileResponse(file, content_type="image/x-icon")


def index(request: HttpRequest) -> HttpResponse:
    template = loader.get_template("landing/index.html")
    return HttpResponse(template.render({}, request))

@login_required
def onboarding_step1(request: HttpRequest) -> HttpResponse:
    return render(request, "onboarding/step1.html")

@login_required
def onboarding_step2(request: HttpRequest) -> HttpResponse:
    return render(request, "onboarding/step2.html")

@login_required
def onboarding_step3(request: HttpRequest) -> HttpResponse:
    return render(request, "onboarding/step3.html")