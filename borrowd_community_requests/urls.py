from django.urls import path

from .views import (
    CommunityRequestCreateView,
    CommunityRequestDismissView,
    CommunityRequestListView,
    CommunityRequestSuccessView,
)

urlpatterns = [
    path("", CommunityRequestListView.as_view(), name="community-request-list"),
    path(
        "create/", CommunityRequestCreateView.as_view(), name="community-request-create"
    ),
    path(
        "<int:pk>/success/",
        CommunityRequestSuccessView.as_view(),
        name="community-request-success",
    ),
    path(
        "<int:pk>/dismiss/",
        CommunityRequestDismissView.as_view(),
        name="community-request-dismiss",
    ),
]
