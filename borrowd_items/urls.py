from django.urls import path

from .views import (
    ItemCreateView,
    ItemDeleteView,
    ItemDetailView,
    ItemListView,
    ItemUpdateView,
)

urlpatterns = [
    path("", ItemListView.as_view(), name="item-list"),
    path("create/", ItemCreateView.as_view(), name="item-create"),
    path("<int:pk>/", ItemDetailView.as_view(), name="item-detail"),
    path("<int:pk>/edit/", ItemUpdateView.as_view(), name="item-edit"),
    path("<int:pk>/delete/", ItemDeleteView.as_view(), name="item-delete"),
]
