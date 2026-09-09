from typing import Any

from django.db.models import QuerySet
from django_filters import CharFilter, FilterSet

from .models import ChatThread


# django-filter is untyped (see the django_filters note in mypy.ini), so
# subclassing it trips strict mode's "subclass of Any" check.
class ConversationFilter(FilterSet):  # type: ignore[misc]
    """Narrow a viewer's conversations. The caller scopes them first."""

    item = CharFilter(label="Item", method="filter_by_item")

    def filter_by_item(
        self, queryset: QuerySet[ChatThread], name: str, value: Any
    ) -> QuerySet[ChatThread]:
        """Match on the Item's name.

        A hard-deleted Item leaves no row to match, so its conversations drop
        out of a name search. A removed Item keeps its name and still matches.
        """
        if not value:
            return queryset
        return queryset.filter(item__name__icontains=value)

    class Meta:
        model = ChatThread
        fields: list[str] = ["item"]
