from datetime import timedelta

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from borrowd_beta.forms import BetaSignupForm
from borrowd_beta.models import BetaSignup


def signup(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = BetaSignupForm(request.POST)
        if form.is_valid():
            beta_code = form.cleaned_data["code"]
            # Save the form data to BetaSignup model
            beta_signup = BetaSignup(beta_code=beta_code)
            beta_signup.save()

            # Set cookie with token and redirect to referrer page
            return set_cookie_response(request, beta_signup)
    else:
        form = BetaSignupForm()

    return render(request, "beta/signup_form.html", {"form": form})


def set_cookie_response(request: HttpRequest, beta_signup: BetaSignup) -> HttpResponse:
    secure = getattr(settings, "BETA_SECURE_COOKIE", False)
    domain = getattr(settings, "BETA_COOKIE_DOMAIN", None)
    samesite = getattr(settings, "BETA_COOKIE_SAMESITE", "Lax")
    response = HttpResponse("Beta signup successful. Redirecting...")
    response["HX-Redirect"] = settings.BETA_SIGNUP_REDIRECT_PATH
    response.set_cookie(
        "beta_key",
        str(beta_signup.token),
        secure=secure,
        domain=domain,
        httponly=True,
        samesite=samesite,  # type: ignore[arg-type]
        max_age=timedelta(days=90),
    )
    return response
