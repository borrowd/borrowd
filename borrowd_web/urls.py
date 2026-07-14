from django.urls import path

from . import views
from .views import (
    onboarding_complete,
    onboarding_step1,
    onboarding_step2,
)

urlpatterns = [
    path("", views.index, name="index"),
    path("onboarding/1/", onboarding_step1, name="onboarding_step1"),
    path("onboarding/2/", onboarding_step2, name="onboarding_step2"),
    path("onboarding/complete/", onboarding_complete, name="onboarding_complete"),
]
