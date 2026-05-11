from typing import Any

from django.db.models import Count, Q, QuerySet
from django_filters import BooleanFilter, CharFilter, FilterSet

from .models import Membership, MembershipStatus


# No typing for django_filter, so mypy doesn't like us subclassing.
class GroupFilter(FilterSet):  # type: ignore[misc]
    search = CharFilter(label="Search", method="filter_by_search")
    moderator_only = BooleanFilter(label="Moderator Only", method="filter_by_moderator")

    def filter_by_search(
        self, queryset: QuerySet[Membership], name: str, value: Any
    ) -> QuerySet[Membership]:
        if not value:
            return queryset
        return queryset.filter(
            Q(group__name__icontains=value) | Q(group__description__icontains=value)
        )

    def filter_by_moderator(
        self, queryset: QuerySet[Membership], name: str, value: bool
    ) -> QuerySet[Membership]:
        if value:
            return queryset.filter(is_moderator=True)
        return queryset

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
            qs = qs.annotate(
                active_member_count=Count(
                    "group__membership",
                    filter=Q(group__membership__status=MembershipStatus.ACTIVE),
                    distinct=True,
                )
            )
            if self.is_bound:
                # ensure form validation before filtering
                self.errors
                qs = self.filter_queryset(qs)
            self._qs = qs
        return self._qs

    class Meta:
        model = Membership
        fields = ["search", "moderator_only"]
