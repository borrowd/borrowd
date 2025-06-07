from typing import Any

from django.db.models import Q, QuerySet
from django_filters import CharFilter, FilterSet

from .models import Membership


# No typing for django_filter, so mypy doesn't like us subclassing.
class GroupFilter(FilterSet):  # type: ignore[misc]
    search = CharFilter(label="Search", method="filter_by_search")

    def filter_by_search(
        self, queryset: QuerySet[Membership], name: str, value: Any
    ) -> QuerySet[Membership]:
        if not value:
            return queryset
        return queryset.filter(
            Q(group__name__icontains=value) | Q(group__description__icontains=value)
        )

    @property
    def qs(self) -> QuerySet[Membership]:
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
            qs: QuerySet[Membership] = Membership.objects.select_related(
                "group"
            ).filter(
                user=self.request.user,
            )
            if self.is_bound:
                # ensure form validation before filtering
                self.errors
                qs = self.filter_queryset(qs)
            self._qs = qs
        return self._qs

    class Meta:
        model = Membership
        fields = ["search"]
