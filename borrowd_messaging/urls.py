from django.urls import path

from .views import ChatThreadDetailView

urlpatterns = [
    path("<int:pk>/", ChatThreadDetailView.as_view(), name="chat-thread-detail"),
]
