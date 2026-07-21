from django.urls import path

from .views import (
    ApproveMemberView,
    BecomeModeratorView,
    DenyMemberView,
    GroupCreateView,
    GroupDetailView,
    GroupInviteView,
    GroupJoinView,
    GroupListView,
    GroupUpdateView,
    LeaveGroupView,
    RemoveMemberView,
)

app_name = "borrowd_groups"

urlpatterns = [
    path("", GroupListView.as_view(), name="group-list"),
    path("create/", GroupCreateView.as_view(), name="group-create"),
    path("<int:pk>/", GroupDetailView.as_view(), name="group-detail"),
    path("<int:pk>/invite/", GroupInviteView.as_view(), name="group-invite"),
    path("<int:pk>/edit/", GroupUpdateView.as_view(), name="group-edit"),
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
    path(
        "<int:pk>/leave/",
        LeaveGroupView.as_view(),
        name="leave-group",
    ),
    path(
        "<int:pk>/become-moderator/",
        BecomeModeratorView.as_view(),
        name="become-moderator",
    ),
    path("join/<str:encoded>/", GroupJoinView.as_view(), name="group-join"),
]
