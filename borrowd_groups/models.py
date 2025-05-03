from typing import Never  # Unfortunately needed for more mypy shenanigans

from django.contrib.auth.models import Group
from django.db.models import (
    CASCADE,
    DO_NOTHING,
    BooleanField,
    DateTimeField,
    ForeignKey,
    IntegerField,
    ManyToManyField,
    Model,
    TextChoices,
    TextField,
)
from django.urls import reverse

from borrowd.models import TrustLevel
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
    users: ManyToManyField[BorrowdUser, BorrowdUser] = ManyToManyField(
        BorrowdUser,
        blank=True,
        help_text="The users in this group.",
        through="borrowd_groups.Membership",
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


class MembershipStatus(TextChoices):
    ACTIVE = ("active", "Active")
    SUSPENDED = ("suspended", "Suspended")
    BANNED = ("banned", "Banned")


class Membership(Model):
    """
    A membership in a :class:`Group`. This is a custom many-to-many
    relationship between :class:`borrowd_users.models.BorrowdUser`s
    and :class:`Group`s, required because we need to track the User's
    Trust Level with each Group.

    Attributes:
        user (ForeignKey[BorrowdUser]): A foreign key to the BorrowdUser model,
            representing the user who is a member of the group.
        group (ForeignKey[Group]): A foreign key to the :class:`Group` model,
            representing the group the user is a member of.
        is_moderator (BooleanField): A boolean field indicating whether the user
            is a moderator of the group. Defaults to False.
    """

    user: ForeignKey[BorrowdUser] = ForeignKey(
        BorrowdUser,
        on_delete=CASCADE,
    )
    group: ForeignKey[BorrowdGroup] = ForeignKey(
        BorrowdGroup,
        on_delete=CASCADE,
    )
    is_moderator: BooleanField[Never, Never] = BooleanField(default=False)
    joined_at: DateTimeField[Never, Never] = DateTimeField(
        auto_now_add=True,
        help_text="The date and time at which the user joined the group.",
    )
    status: TextField[MembershipStatus, str] = TextField(
        choices=MembershipStatus.choices,
        default=MembershipStatus.ACTIVE,
        null=False,
        blank=False,
    )
    status_changed_at: DateTimeField[Never, Never] = DateTimeField(
        null=True,
        blank=False,
        help_text="The date and time at which the membership status was last updated.",
    )
    status_changed_reason: TextField[str, str] = TextField(
        max_length=500,
        null=True,
        blank=False,
        help_text=(
            "The reason for which the status was last updated. "
            "May be useful in unfortunate cases of suspension / banning."
        ),
    )
    trust_level: IntegerField[Never, Never] = IntegerField(
        choices=TrustLevel,
        help_text="The User's selected level of Trust for the given Group.",
    )
