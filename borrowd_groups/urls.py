from django.urls import path

from .views import (
    GroupCreateView,
    GroupDeleteView,
    GroupDetailView,
    GroupInviteView,
    GroupJoinView,
    GroupListView,
    GroupUpdateView,
)

app_name = "borrowd_groups"

urlpatterns = [
    path("", GroupListView.as_view(), name="group-list"),
    path("create/", GroupCreateView.as_view(), name="group-create"),
    path("<int:pk>/", GroupDetailView.as_view(), name="group-detail"),
    path("<int:pk>/invite/", GroupInviteView.as_view(), name="group-invite"),
    path("<int:pk>/edit/", GroupUpdateView.as_view(), name="group-edit"),
    path("<int:pk>/delete/", GroupDeleteView.as_view(), name="group-delete"),
    path("join/<str:encoded>/", GroupJoinView.as_view(), name="group-join"),
]

handler403 = "borrowd_groups.views.forbidden"
