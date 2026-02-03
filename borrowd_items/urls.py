from django.urls import path

from .views import (
    ItemCreateView,
    ItemDeleteView,
    ItemDetailView,
    ItemListView,
    ItemPhotoCreateView,
    ItemPhotoDeleteView,
    ItemUpdateView,
    borrow_item,
    get_item_card,
)

urlpatterns = [
    path("", ItemListView.as_view(), name="item-list"),
    path("create/", ItemCreateView.as_view(), name="item-create"),
    path("<int:pk>/", ItemDetailView.as_view(), name="item-detail"),
    path("<int:pk>/edit/", ItemUpdateView.as_view(), name="item-edit"),
    path("<int:pk>/delete/", ItemDeleteView.as_view(), name="item-delete"),
    path("<int:pk>/borrow/", borrow_item, name="item-borrow"),
    path("<int:pk>/card/", get_item_card, name="item-card"),
    path(
        "<int:item_pk>/photos/upload/",
        ItemPhotoCreateView.as_view(),
        name="itemphoto-create",
    ),
    path(
        "<int:item_pk>/photos/delete/<int:pk>",
        ItemPhotoDeleteView.as_view(),
        name="itemphoto-delete",
    ),
]
