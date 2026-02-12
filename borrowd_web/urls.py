from django.urls import path
from .views import onboarding_step1
from .views import onboarding_step2
from .views import onboarding_step3
from .views import onboarding_complete
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("onboarding/1/", onboarding_step1, name="onboarding_step1"),
    path("onboarding/2/", onboarding_step2, name="onboarding_step2"),
    path("onboarding/3/", onboarding_step3, name="onboarding_step3"),
    path("onboarding/complete/", onboarding_complete, name="onboarding_complete")
]
