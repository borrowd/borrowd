from django.urls import path

from .views import (
    ChatThreadDetailView,
    ChatThreadListView,
    ChatThreadPollView,
    ChatThreadPreRequestCloseView,
    ChatThreadPreRequestOpenView,
    ChatThreadReadView,
    ChatThreadSendView,
    ChatThreadUnreadBadgeView,
)

urlpatterns = [
    path("", ChatThreadListView.as_view(), name="chat-thread-list"),
    path(
        "unread-badge/",
        ChatThreadUnreadBadgeView.as_view(),
        name="chat-thread-unread-badge",
    ),
    path(
        "items/<int:item_pk>/open/",
        ChatThreadPreRequestOpenView.as_view(),
        name="chat-thread-pre-request-open",
    ),
    path("<int:pk>/", ChatThreadDetailView.as_view(), name="chat-thread-detail"),
    path("<int:pk>/send/", ChatThreadSendView.as_view(), name="chat-thread-send"),
    path("<int:pk>/poll/", ChatThreadPollView.as_view(), name="chat-thread-poll"),
    path("<int:pk>/read/", ChatThreadReadView.as_view(), name="chat-thread-read"),
    path(
        "<int:pk>/pre-request-close/",
        ChatThreadPreRequestCloseView.as_view(),
        name="chat-thread-pre-request-close",
    ),
]
