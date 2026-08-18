from django.urls import path

from .views import (
    CommunityRequestCancelView,
    CommunityRequestCreateView,
    CommunityRequestDismissView,
    CommunityRequestListView,
    CommunityRequestMarkFulfilledView,
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
    path(
        "<int:pk>/cancel/",
        CommunityRequestCancelView.as_view(),
        name="community-request-cancel",
    ),
    path(
        "<int:pk>/mark-fulfilled/",
        CommunityRequestMarkFulfilledView.as_view(),
        name="community-request-mark-fulfilled",
    ),
]
