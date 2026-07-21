from django.urls import path

from .push_views import subscribe_push, unsubscribe_push, vapid_public_key

urlpatterns = [
    path("subscribe/", subscribe_push, name="push-subscribe"),
    path("unsubscribe/", unsubscribe_push, name="push-unsubscribe"),
    path("vapid-public-key/", vapid_public_key, name="push-vapid-key"),
]
