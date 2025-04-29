from typing import Never  # Unfortunately needed for more mypy shenanigans

from django.contrib.auth.models import Group
from django.db.models import (
    BooleanField,
    TextField,
)
from django.urls import reverse


class BorrowdGroup(Group):
    """
    A group of users. This is a subclass of Django's built-in Group
    model. There is no clean and widely-accepted way of using a
    custom group model in Django, but this is a common way to start.
    """

    description: TextField[Never, Never] = TextField(blank=True, null=True)
    membership_requires_approval: BooleanField[Never, Never] = BooleanField(
        default=True,
        help_text="If true, new members will require Moderator approval to join the group.",
    )

    def get_absolute_url(self) -> str:
        return reverse("borrowd_groups:group-detail", args=[self.pk])
