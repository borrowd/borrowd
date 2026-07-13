from typing import Any  # Unfortunately needed for more mypy shenanigans

from django.contrib.auth.models import Group
from django.db.models import (
    CASCADE,
    DO_NOTHING,
    SET_NULL,
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKey,
    IntegerField,
    Manager,
    ManyToManyField,
    Model,
    OneToOneField,
    TextChoices,
    TextField,
    UniqueConstraint,
)
from django.urls import reverse
from imagekit.models import ProcessedImageField
from imagekit.processors import ResizeToFit

from borrowd_groups.exceptions import ExistingMemberException
from borrowd_permissions.models import BorrowdGroupOLP
from borrowd_users.models import BorrowdUser


class BorrowdGroupManager(Manager["BorrowdGroup"]):
    def create_group(
        self,
        **kwargs: Any,
    ) -> "BorrowdGroup":

        group: BorrowdGroup = BorrowdGroup(**kwargs)

        # And finally, this is what triggers the post_save signal,
        # and the instance that's received will have our special
        # instance property as set above, which we only need at the
        # point of creation. Of course, whenever this object is
        # re-loaded from the database later, it will be "normal",
        # i.e. no secret smuggled properties, just standard ones :)
        group.save(using=self._db)

        return group


class BorrowdGroup(Model):
    """
    A group of users. This is a subclass of Django's built-in Group
    model. There is no clean and widely-accepted way of using a
    custom group model in Django, but this is a common way to start.
    """

    name = CharField(max_length=50)
    description = TextField(max_length=500, blank=True, null=True)
    logo = ProcessedImageField(
        upload_to="groups/logos/",
        processors=[ResizeToFit(1600, 1600)],
        format="JPEG",
        options={"quality": 75},
        null=True,
        blank=True,
    )
    banner = ProcessedImageField(
        upload_to="groups/banners/",
        processors=[ResizeToFit(1600, 400)],
        format="JPEG",
        options={"quality": 75},
        null=True,
        blank=True,
    )
    membership_requires_approval = BooleanField(
        default=True,
        help_text="New members require Moderator approval to join the group",
    )
    users = ManyToManyField(
        BorrowdUser,
        blank=True,
        help_text="The users in this group.",
        related_name="borrowd_groups",
        related_query_name="borrowd_groups",
        through="borrowd_groups.Membership",
    )
    perms_group = OneToOneField(
        Group,
        null=True,
        on_delete=CASCADE,
    )
    created_by = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The user who created the group.",
        on_delete=DO_NOTHING,
    )
    created_at = DateTimeField(
        auto_now_add=True,
        help_text="The date and time at which the group was created.",
    )
    updated_by = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The last user who updated the group.",
        on_delete=DO_NOTHING,
    )
    updated_at = DateTimeField(
        auto_now=True,
        help_text="The date and time at which the group was last updated.",
    )
    deleted_at = DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text="Set when the record is soft-deleted. NULL means active.",
    )
    deleted_by = ForeignKey(
        BorrowdUser,
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="+",
        help_text="Who performed the soft-delete. NULL means active or unknown.",
    )

    # Override default manager to have custom `create()` method,
    # which allows us to pass the trust level to the Membership
    # model via the post_save signal.
    # mypy error: Cannot override class variable (previously declared on base class "Group") with instance variable  [misc]
    # ... but, this is a class variable, not an instance variable, right?
    objects = BorrowdGroupManager()

    def get_absolute_url(self) -> str:
        return reverse("borrowd_groups:group-detail", args=[self.pk])

    @property
    def needs_moderator(self) -> bool:
        """
        Return True when the group has active members
        but no active moderator.
        """
        active_memberships = Membership.objects.filter(
            group=self,
            status=MembershipStatus.ACTIVE,
        )

        return (
            active_memberships.exists()
            and not active_memberships.filter(is_moderator=True).exists()
        )

    def add_user(
        self, user: BorrowdUser, is_moderator: bool = False
    ) -> "Membership":
        """
        Add a user to the group.
        """
        # TODO: Check for suspended, banned etc.
        if Membership.objects.filter(user=user, group=self).exists():
            raise ExistingMemberException(
                (f"User '{user}' is already a member of group '{self}'")
            )

        if self.membership_requires_approval and not is_moderator:
            default_status = MembershipStatus.PENDING
        else:
            default_status = MembershipStatus.ACTIVE

        membership: Membership = Membership.objects.create(
            user=user,
            group=self,
            trust_level=trust_level,
            status=default_status,
            is_moderator=is_moderator,
        )

        return membership

    def remove_user(
        self,
        user: BorrowdUser,
        bypass_last_moderator_check: bool = False,
    ) -> None:
        """
        Remove a user from the group.
        """
        membership: Membership = Membership.objects.get(user=user, group=self)

        # Allow specific flows, such as leaving a group, to bypass the
        # last-moderator signal check.
        if bypass_last_moderator_check:
            setattr(membership, "_bypass_last_moderator_check", True)

        # Remove the user's group membership.
        perms_group = self.perms_group
        if perms_group is None:
            raise ValueError(
                "This BorrowdGroup has no perms_group; cannot remove membership."
            )
        user.groups.remove(perms_group)

        # Remove the group membership record.
        membership.delete()

    def update_user_membership(
        self,
        user: BorrowdUser,
        is_moderator: bool | None = None,
    ) -> None:
        """
        Update a user's membership in the group.
        """
        membership: Membership = Membership.objects.get(user=user, group=self)

        if is_moderator is not None:
            membership.is_moderator = is_moderator

        membership.save()

        # TODO: Gracefuly soft delete when the last user quits.

    class Meta:
        permissions = (
            (BorrowdGroupOLP.VIEW, "Can view this Group"),
            (BorrowdGroupOLP.EDIT, "Can edit this Group"),
            (BorrowdGroupOLP.DELETE, "Can delete this Group"),
        )
        constraints = [
            UniqueConstraint(fields=["name", "created_by"], name="unique_group_by_user")
        ]


class MembershipStatus(TextChoices):
    PENDING = ("PENDING", "Pending")
    ACTIVE = ("ACTIVE", "Active")
    SUSPENDED = ("SUSPENDED", "Suspended")
    BANNED = ("BANNED", "Banned")
    ENDED = ("ENDED", "Ended")


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

    user = ForeignKey(
        BorrowdUser,
        on_delete=CASCADE,
    )
    group = ForeignKey(
        BorrowdGroup,
        on_delete=CASCADE,
    )
    is_moderator = BooleanField(default=False)
    joined_at = DateTimeField(
        auto_now_add=True,
        help_text="The date and time at which the user joined the group.",
    )
    status = TextField(
        choices=MembershipStatus.choices,
        null=False,
        blank=False,
    )
    _previous_status: str | None = None
    status_changed_at = DateTimeField(
        null=True,
        blank=False,
        help_text="The date and time at which the membership status was last updated.",
    )
    status_changed_reason = TextField(
        max_length=500,
        null=True,
        blank=False,
        help_text=(
            "The reason for which the status was last updated. "
            "May be useful in unfortunate cases of suspension / banning."
        ),
    )

    class Meta:
        constraints = [
            UniqueConstraint(fields=["user", "group"], name="unique_membership")
        ]
