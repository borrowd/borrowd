from django.urls import path

from .views import (
    ApproveMemberView,
    DenyMemberView,
    GroupCreateView,
    GroupDeleteView,
    GroupDetailView,
    GroupInviteView,
    GroupJoinView,
    GroupListView,
    GroupUpdateView,
    RemoveMemberView,
    UpdateTrustLevelView,
)

app_name = "borrowd_groups"

urlpatterns = [
    path("", GroupListView.as_view(), name="group-list"),
    path("create/", GroupCreateView.as_view(), name="group-create"),
    path("<int:pk>/", GroupDetailView.as_view(), name="group-detail"),
    path("<int:pk>/invite/", GroupInviteView.as_view(), name="group-invite"),
    path("<int:pk>/edit/", GroupUpdateView.as_view(), name="group-edit"),
    path("<int:pk>/delete/", GroupDeleteView.as_view(), name="group-delete"),
    path(
        "<int:pk>/update-trust-level/",
        UpdateTrustLevelView.as_view(),
        name="update-trust-level",
    ),
    path(
        "<int:pk>/remove-member/<int:user_id>/",
        RemoveMemberView.as_view(),
        name="remove-member",
    ),
    path( 
        "membership/<int:membership_id>/approve/", 
        ApproveMemberView.as_view(),
        name="approve-member",
    ),
    path(
        "membership/<int:membership_id>/deny/",
        DenyMemberView.as_view(),
        name="deny-member",
    ),
    path("join/<str:encoded>/", GroupJoinView.as_view(), name="group-join"),
]
