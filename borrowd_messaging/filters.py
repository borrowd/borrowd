from typing import Any

from django.db.models import Q, QuerySet
from django_filters import CharFilter, FilterSet

from borrowd_users.request import get_authenticated_user

from .models import ChatThread


# django-filter is untyped (see the django_filters note in mypy.ini), so
# subclassing it trips strict mode's "subclass of Any" check.
class ConversationFilter(FilterSet):  # type: ignore[misc]
    """Narrow a viewer's conversations. The caller scopes them first."""

    item = CharFilter(label="Item", method="filter_by_item")
    person = CharFilter(label="Person", method="filter_by_person")

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

    def filter_by_person(
        self, queryset: QuerySet[ChatThread], name: str, value: Any
    ) -> QuerySet[ChatThread]:
        """Match the other participant on any part of their name.

        `Profile.full_name` is built in Python, so there is no single column to
        search. Every word has to match a first or last name instead, which
        makes "ada lovelace" and "lovelace ada" both find the same person.
        """
        if not value:
            return queryset
        viewer = get_authenticated_user(self.request)
        for term in value.split():
            queryset = queryset.filter(
                (
                    Q(borrower=viewer)
                    & (
                        Q(lender__first_name__icontains=term)
                        | Q(lender__last_name__icontains=term)
                    )
                )
                | (
                    Q(lender=viewer)
                    & (
                        Q(borrower__first_name__icontains=term)
                        | Q(borrower__last_name__icontains=term)
                    )
                )
            )
        return queryset

    class Meta:
        model = ChatThread
        fields: list[str] = ["item", "person"]
