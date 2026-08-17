from django.urls import path

from .views import ChatThreadDetailView, ChatThreadPollView, ChatThreadSendView

urlpatterns = [
    path("<int:pk>/", ChatThreadDetailView.as_view(), name="chat-thread-detail"),
    path("<int:pk>/send/", ChatThreadSendView.as_view(), name="chat-thread-send"),
    path("<int:pk>/poll/", ChatThreadPollView.as_view(), name="chat-thread-poll"),
]
