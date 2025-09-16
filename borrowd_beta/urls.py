from django.urls import path

from borrowd_beta import views

urlpatterns = [
    path("signup/", views.signup, name="beta-signup"),
]
