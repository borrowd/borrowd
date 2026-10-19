from typing import Any  # Unfortunately needed for more mypy shenanigans

from django.contrib.auth.models import Group
from django.core.validators import FileExtensionValidator
from django.db import transaction
from django.db.models import (
    CASCADE,
    DO_NOTHING,
    SET_NULL,
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKey,
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

from borrowd.validators import ALLOWED_IMAGE_EXTENSIONS, validate_image_size
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

    _perms_group_id_for_cleanup: int | None

    name = CharField(max_length=50)
    description = TextField(max_length=500, blank=True, null=True)
    logo = ProcessedImageField(
        upload_to="groups/logos/",
        processors=[ResizeToFit(1600, 1600)],
        format="JPEG",
        options={"quality": 75},
        validators=[
            FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS),
            validate_image_size,
        ],
        null=True,
        blank=True,
    )
    banner = ProcessedImageField(
        upload_to="groups/banners/",
        processors=[ResizeToFit(1600, 400)],
        format="JPEG",
        options={"quality": 75},
        validators=[
            FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS),
            validate_image_size,
        ],
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

    def add_user(self, user: BorrowdUser, is_moderator: bool = False) -> "Membership":
        """
        Add a user to the group.
        """
        # TODO: Check for suspended, banned etc.
        if Membership.objects.filter(user=user, group=self).exists():
            raise ExistingMemberException(
                f"User '{user}' is already a member of group '{self}'"
            )

        if self.membership_requires_approval and not is_moderator:
            default_status = MembershipStatus.PENDING
        else:
            default_status = MembershipStatus.ACTIVE

        # add_user() has exactly two callers: the group-creation signal
        # (the creator's own membership) and the invite-accept view. An
        # invite link is the only way to join an existing group today, so
        # anything that isn't the creator joined via invite.
        join_method = (
            MembershipJoinMethod.GROUP_CREATOR
            if user.pk == self.created_by_id
            else MembershipJoinMethod.JOINED_GROUP
        )

        membership: Membership = Membership.objects.create(
            user=user,
            group=self,
            status=default_status,
            is_moderator=is_moderator,
            join_method=join_method,
        )

        return membership

    def remove_user(
        self,
        user: BorrowdUser,
        bypass_last_moderator_check: bool = False,
        removed_by: BorrowdUser | None = None,
        reason: "DepartureReason | None" = None,
    ) -> None:
        """
        Remove a user from the group.

        `removed_by` is the moderator performing the removal; leave it
        NULL when the user is leaving on their own. `reason` defaults to
        inferring LEFT_VOLUNTARILY/REMOVED_BY_MODERATOR from `removed_by`;
        pass it explicitly for a departure that's neither, such as the
        user's account being closed.
        """
        resolved_reason = reason or (
            DepartureReason.REMOVED_BY_MODERATOR
            if removed_by
            else DepartureReason.LEFT_VOLUNTARILY
        )
        with transaction.atomic():
            membership: Membership = Membership.objects.get(user=user, group=self)

            # Allow specific flows, such as leaving a group, to bypass the
            # last-moderator signal check.
            if bypass_last_moderator_check:
                membership._bypass_last_moderator_check = True

            # Remove the user's group membership.
            perms_group = self.perms_group
            if perms_group is None:
                raise ValueError(
                    "This BorrowdGroup has no perms_group; cannot remove membership."
                )
            user.groups.remove(perms_group)

            # Recorded immediately before the hard delete, inside the same
            # atomic block: if the delete below fails (e.g. the last-
            # moderator check), this rolls back along with it.
            MembershipDeparture.objects.create(
                user=membership.user,
                username=membership.user.username,
                group=self,
                group_name=self.name,
                joined_at=membership.joined_at,
                departure_reason=resolved_reason,
                removed_by=removed_by,
            )
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


class MembershipJoinMethod(TextChoices):
    GROUP_CREATOR = ("GROUP_CREATOR", "Created the group")
    JOINED_GROUP = ("JOINED_GROUP", "Joined the group")


class Membership(Model):
    """
    A membership in a :class:`Group`. This is a custom many-to-many
    relationship between :class:`borrowd_users.models.BorrowdUser`s
    and :class:`Group`s

    Attributes:
        user (ForeignKey[BorrowdUser]): A foreign key to the BorrowdUser model,
            representing the user who is a member of the group.
        group (ForeignKey[Group]): A foreign key to the :class:`Group` model,
            representing the group the user is a member of.
        is_moderator (BooleanField): A boolean field indicating whether the user
            is a moderator of the group. Defaults to False.
    """

    _bypass_last_moderator_check: bool

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
    join_method = CharField(
        max_length=20,
        choices=MembershipJoinMethod.choices,
        null=True,
        blank=True,
        default=None,
        help_text=(
            "How this membership began. NULL for memberships predating this "
            "field, or whose group's creator couldn't be determined."
        ),
    )

    class Meta:
        constraints = [
            UniqueConstraint(fields=["user", "group"], name="unique_membership")
        ]


class DepartureReason(TextChoices):
    """
    Why a Membership ended via BorrowdGroup.remove_user(). Distinguishes a
    member's own choice to leave from their account being closed out from
    under them, which `removed_by` alone can't: both leave it NULL.
    """

    LEFT_VOLUNTARILY = ("left_voluntarily", "Left the group voluntarily")
    REMOVED_BY_MODERATOR = ("removed_by_moderator", "Removed by a moderator")
    ACCOUNT_DELETED = ("account_deleted", "Closed their account")


class MembershipDeparture(Model):
    """
    One row per membership that ends via the hard delete BorrowdGroup
    remove_user() performs, preserving what that delete otherwise loses:
    who was in the group, how long, and whether they left or were removed.

    `user` and `group` are SET_NULL rather than CASCADE: a later hard
    delete of either (an account purge, a group's last member leaving)
    must not silently erase this history. The username/group_name
    snapshots keep each row legible even once that happens.
    """

    user = ForeignKey(
        BorrowdUser,
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="+",
    )
    username = CharField(
        max_length=150,
        help_text=(
            "The departed user's username at the time they left, kept in "
            "case `user` is later hard-deleted or anonymized."
        ),
    )
    group = ForeignKey(
        BorrowdGroup,
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="+",
    )
    group_name = CharField(
        max_length=50,
        help_text="The group's name at the time of departure, kept in case `group` is later hard-deleted.",
    )
    joined_at = DateTimeField(help_text="The departed membership's original joined_at.")
    left_at = DateTimeField(
        auto_now_add=True,
        help_text="When the membership was removed.",
    )
    departure_reason = CharField(
        max_length=32,
        choices=DepartureReason.choices,
        help_text="Why the membership ended.",
    )
    removed_by = ForeignKey(
        BorrowdUser,
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="+",
        help_text="The moderator who removed this member. NULL when they left voluntarily or closed their account.",
    )
