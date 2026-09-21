from __future__ import annotations

from typing import Any, ClassVar

from django.db.models import Case, F, Q, QuerySet, When
from django.forms import CheckboxInput
from django_filters import BooleanFilter, CharFilter, FilterSet
from django_stubs_ext import WithAnnotations

from borrowd_users.request import get_authenticated_user

from .models import ChatThread
from .read_state import ThreadReadState


class _UnreadCheckboxInput(CheckboxInput):
    """A checkbox whose bookmarked query value stays honest when hand-edited.

    A real checkbox only ever submits "on" (checked) or nothing (unchecked),
    but this filter's URL is meant to be bookmarkable, so a hand-edited
    "?unread=0" must also read as unchecked rather than as CheckboxInput's
    default fallback of `bool("0")`, which is True.
    """

    _FALSY_VALUES: ClassVar[set[str]] = {"0", "no", "off"}

    def value_from_datadict(self, data: Any, files: Any, name: str) -> bool:
        value = data.get(name)
        if isinstance(value, str) and value.lower() in self._FALSY_VALUES:
            return False
        return super().value_from_datadict(data, files, name)


_PERSON_SEARCH_MAX_TERMS = 4


# django-filter is untyped (see the django_filters note in mypy.ini), so
# subclassing it trips strict mode's "subclass of Any" check.
class ConversationFilter(FilterSet):  # type: ignore[misc]
    """Narrow a viewer's conversations. The caller scopes them first."""

    item = CharFilter(label="Item", method="filter_by_item")
    person = CharFilter(label="Person", method="filter_by_person")
    unread = BooleanFilter(
        label="Unread only", method="filter_by_unread", widget=_UnreadCheckboxInput
    )

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
        Only the first few distinct words count, so the query stays small.
        """
        if not value:
            return queryset
        viewer = get_authenticated_user(self.request)
        queryset = queryset.alias(
            other_first_name=Case(
                When(lender=viewer, then=F("borrower__first_name")),
                default=F("lender__first_name"),
            ),
            other_last_name=Case(
                When(lender=viewer, then=F("borrower__last_name")),
                default=F("lender__last_name"),
            ),
        )
        # icontains ignores case, so "Ada ada" is one word.
        terms = list(dict.fromkeys(value.lower().split()))[:_PERSON_SEARCH_MAX_TERMS]
        return queryset.filter(
            *(
                Q(other_first_name__icontains=term) | Q(other_last_name__icontains=term)
                for term in terms
            )
        )

    def filter_by_unread(
        self,
        queryset: QuerySet[WithAnnotations[ChatThread, ThreadReadState]],
        name: str,
        value: Any,
    ) -> QuerySet[WithAnnotations[ChatThread, ThreadReadState]]:
        """Keep only conversations this viewer has not acknowledged.

        The caller must have annotated the threads through
        `threads_with_unread_state`, which the hub query does.

        Archived conversations can be unread too: a closing notice counts until
        each participant acknowledges it.
        """
        if not value:
            return queryset
        return queryset.filter(has_unread_messages=True)

    class Meta:
        model = ChatThread
        fields: list[str] = ["item", "person", "unread"]
