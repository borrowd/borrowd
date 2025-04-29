from typing import Never  # Unfortunately needed for more mypy shenanigans

from django.contrib.auth.models import Group
from django.db.models import (
    DO_NOTHING,
    BooleanField,
    DateTimeField,
    ForeignKey,
    TextField,
)
from django.urls import reverse

from borrowd_users.models import BorrowdUser


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
    created_by: ForeignKey[BorrowdUser] = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The user who created the group.",
        on_delete=DO_NOTHING,
    )
    created_at: DateTimeField[Never, Never] = DateTimeField(
        auto_now_add=True,
        help_text="The date and time at which the group was created.",
    )
    updated_by: ForeignKey[BorrowdUser] = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The last user who updated the group.",
        on_delete=DO_NOTHING,
    )
    updated_at: DateTimeField[Never, Never] = DateTimeField(
        auto_now=True,
        help_text="The date and time at which the group was last updated.",
    )

    def get_absolute_url(self) -> str:
        return reverse("borrowd_groups:group-detail", args=[self.pk])
