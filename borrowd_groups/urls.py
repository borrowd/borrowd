from django.urls import path

from .views import (
    GroupCreateView,
    GroupDeleteView,
    GroupDetailView,
    GroupListView,
    GroupUpdateView,
)

app_name = "borrowd_groups"

urlpatterns = [
    path("", GroupListView.as_view(), name="group-list"),
    path("create/", GroupCreateView.as_view(), name="group-create"),
    path("<int:pk>/", GroupDetailView.as_view(), name="group-detail"),
    path("<int:pk>/edit/", GroupUpdateView.as_view(), name="group-edit"),
    path("<int:pk>/delete/", GroupDeleteView.as_view(), name="group-delete"),
]
