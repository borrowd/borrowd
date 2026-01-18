# my_app/views.py
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


# we need to enforce app-specific 403 errors here :(
def custom_403_router(
    request: HttpRequest, exception: Exception | None = None
) -> HttpResponse:
    if request.path.startswith("/groups/"):
        template = "groups/403.html"
    else:
        template = "403.html"

    return render(request, template, status=403)
