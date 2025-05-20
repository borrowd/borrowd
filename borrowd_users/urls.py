from django.urls import path
from .views import ProfileUpdateView, profile_view

urlpatterns = [
    path("", profile_view, name="profile"),

    path("edit/", ProfileUpdateView.as_view(), name="profile-edit"),
]
