from typing import Any

from django.db.models import Q, QuerySet
from django_filters import CharFilter, FilterSet

from .models import Item


# No typing for django_filter, so mypy doesn't like us subclassing.
class ItemFilter(FilterSet):  # type: ignore[misc]
    search = CharFilter(label="Search", method="filter_by_search")

    def filter_by_search(
        self, queryset: QuerySet[Item], name: str, value: Any
    ) -> QuerySet[Item]:
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(description__icontains=value)
        )

    class Meta:
        model = Item
        fields = ["category", "search"]
