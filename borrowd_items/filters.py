from typing import Any

from django.db.models import Q, QuerySet
from django_filters import CharFilter, FilterSet, ModelChoiceFilter
from guardian.shortcuts import get_objects_for_user

from .models import Item, ItemCategory


# No typing for django_filter, so mypy doesn't like us subclassing.
class ItemFilter(FilterSet):  # type: ignore[misc]
    search = CharFilter(label="Search", method="filter_by_search")
    category = ModelChoiceFilter(
        queryset=ItemCategory.objects.all(), empty_label="Category"
    )

    def filter_by_search(
        self, queryset: QuerySet[Item], name: str, value: Any
    ) -> QuerySet[Item]:
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(description__icontains=value)
        )

    @property
    def qs(self) -> QuerySet[Item]:
        """
        Override the qs property to filter the queryset based on user
        permissions.

        The overall structure of this method mirrors the caching
        mechanism of the original that we're overriding here. The
        main magic is using `django-guardian`'s `get_objects_for_user`
        shortcut to filter the queryset based on the user's
        permissions.

        It's possible we could have achieved the same outcome by
        setting the `queryset` attribute, but it was less clear
        when this is accessed & updated; the `qs` property seemed
        closer to a "public API".
        """
        if not hasattr(self, "_qs"):
            qs: QuerySet[Item] = get_objects_for_user(
                self.request.user,
                "view_this_item",
                klass=Item,
                with_superuser=False,
            )
            if self.is_bound:
                # ensure form validation before filtering
                self.errors
                qs = self.filter_queryset(qs)
            self._qs = qs
        return self._qs

    class Meta:
        model = Item
        fields = ["category", "search"]
