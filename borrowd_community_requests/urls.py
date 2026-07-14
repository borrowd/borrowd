from django.urls import path

from .views import CommunityRequestCreateView, CommunityRequestSuccessView

urlpatterns = [
    path(
        "create/", CommunityRequestCreateView.as_view(), name="community-request-create"
    ),
    path(
        "<int:pk>/success/",
        CommunityRequestSuccessView.as_view(),
        name="community-request-success",
    ),
]
