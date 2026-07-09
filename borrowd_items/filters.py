from typing import Any

from django.db.models import Q, QuerySet
from django_filters import CharFilter, FilterSet, ModelMultipleChoiceFilter
from guardian.shortcuts import get_objects_for_user

from borrowd_permissions.models import ItemOLP
from borrowd_users.request import get_authenticated_user

from .models import Item, ItemCategory


# django-filter is untyped (see the django_filters note in mypy.ini), so
# subclassing it trips strict mode's "subclass of Any" check.
class ItemFilter(FilterSet):  # type: ignore[misc]
    search = CharFilter(label="Search", method="filter_by_search")
    categories = ModelMultipleChoiceFilter(
        field_name="categories",
        queryset=ItemCategory.objects.all(),
        method="filter_by_categories",
        label="Categories",
    )

    def filter_by_search(
        self, queryset: QuerySet[Item], name: str, value: Any
    ) -> QuerySet[Item]:
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(description__icontains=value)
        )

    def filter_by_categories(
        self, queryset: QuerySet[Item], name: str, value: Any
    ) -> QuerySet[Item]:
        """
        Filter items by selected categories.

        Items can have multiple categories assigned.
        When filtering by multiple categories, we show items that match ANY
        of the selected categories, not all of them.

        The `distinct()` call removes items with multiple selected categories
        For example, if a user selects both "Electronics" and "Tools" categories,
        and a "Cordless Drill" item has both categories assigned,
        that item would appear twice in the results without distinct().
        """
        if not value:
            return queryset
        return queryset.filter(categories__in=value).distinct()

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
            qs: QuerySet[Item] = (
                get_objects_for_user(
                    get_authenticated_user(self.request),
                    ItemOLP.VIEW,
                    klass=Item,
                    with_superuser=False,
                )
                .filter(deleted_at__isnull=True)
                .exclude(owner=get_authenticated_user(self.request))
            )
            if self.is_bound:
                # ensure form validation before filtering
                self.errors
                qs = self.filter_queryset(qs)
            # Stable ordering keeps page boundaries deterministic; pk breaks created_at ties.
            self._qs = qs.order_by("-created_at", "-pk")
        return self._qs

    class Meta:
        model = Item
        fields = ["categories", "search"]
