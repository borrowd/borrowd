from typing import Any, Never  # Unfortunately needed for more mypy shenanigans

from django.contrib.auth.models import Group
from django.db.models import (
    CASCADE,
    DO_NOTHING,
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

from borrowd.models import TrustLevel
from borrowd_groups.exceptions import ExistingMemberException
from borrowd_permissions.models import BorrowdGroupOLP
from borrowd_users.models import BorrowdUser


class BorrowdGroupManager(Manager["BorrowdGroup"]):
    def create(
        self,
        **kwargs: Any,
    ) -> "BorrowdGroup":
        """
        Custom create method in order to pass trust_level to the
        Membership model, via signal, when creating a new group.
        """
        # Pop the "trust_level" out of the kwargs, if present, as the
        # underlying model does not expect it.
        trust_level: TrustLevel | None = kwargs.pop("trust_level", None)

        # Manually create the BorrowdGroup object which we'll try to
        # persist. This is the part which would fail if we passed
        # unexpected args like "trust_level".
        group: BorrowdGroup = BorrowdGroup(**kwargs)

        # This instance property is not saved to the database, but
        # is used in the post_save signal to set the trust level
        # between the group and the user that created it.
        setattr(group, "_temp_trust_level", trust_level)

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

    name: CharField[str, str] = CharField(max_length=50, unique=True)
    description: TextField[Never, Never] = TextField(
        max_length=500, blank=True, null=True
    )
    logo: ProcessedImageField = ProcessedImageField(
        upload_to="groups/logos/",
        processors=[ResizeToFit(1600, 1600)],
        format="JPEG",
        options={"quality": 75},
        null=True,
        blank=True,
    )
    banner: ProcessedImageField = ProcessedImageField(
        upload_to="groups/banners/",
        processors=[ResizeToFit(1600, 400)],
        format="JPEG",
        options={"quality": 75},
        null=True,
        blank=True,
    )
    membership_requires_approval: BooleanField[Never, Never] = BooleanField(
        default=True,
        help_text="New members require Moderator approval to join the group",
    )
    users: ManyToManyField[BorrowdUser, BorrowdUser] = ManyToManyField(
        BorrowdUser,
        blank=True,
        help_text="The users in this group.",
        related_name="borrowd_groups",
        related_query_name="borrowd_groups",
        through="borrowd_groups.Membership",
    )
    perms_group: OneToOneField[Group] = OneToOneField(
        Group,
        null=True,
        on_delete=CASCADE,
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

    # Override default manager to have custom `create()` method,
    # which allows us to pass the trust level to the Membership
    # model via the post_save signal.
    # mypy error: Cannot override class variable (previously declared on base class "Group") with instance variable  [misc]
    # ... but, this is a class variable, not an instance variable, right?
    objects: BorrowdGroupManager = BorrowdGroupManager()  # type: ignore[misc]

    def get_absolute_url(self) -> str:
        return reverse("borrowd_groups:group-detail", args=[self.pk])

    def add_user(
        self, user: BorrowdUser, trust_level: TrustLevel, is_moderator: bool = False
    ) -> "Membership":
        """
        Add a user to the group.
        """
        # TODO: Check for suspended, banned etc.
        if Membership.objects.filter(user=user, group=self).exists():
            raise ExistingMemberException(
                (f"User '{user}' is already a member of group '{self}'")
            )

        if self.membership_requires_approval:
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

        perms_group = Group.objects.get(name=self.name)
        user.groups.add(perms_group)

        return membership

    def remove_user(self, user: BorrowdUser) -> None:
        """
        Remove a user from the group.
        """
        perms_group = Group.objects.get(name=self.name)
        user.groups.remove(perms_group)
        Membership.objects.get(user=user, group=self).delete()

    def update_user_membership(
        self,
        user: BorrowdUser,
        trust_level: TrustLevel | None = None,
        is_moderator: bool | None = None,
    ) -> None:
        """
        Update a user's membership in the group.
        """
        membership: Membership = Membership.objects.get(user=user, group=self)

        if trust_level is not None:
            membership.trust_level = trust_level
        if is_moderator is not None:
            membership.is_moderator = is_moderator

        membership.save()

    class Meta:
        permissions = (
            (BorrowdGroupOLP.VIEW, "Can view this Group"),
            (BorrowdGroupOLP.EDIT, "Can edit this Group"),
            (BorrowdGroupOLP.DELETE, "Can delete this Group"),
        )


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

    user: ForeignKey[BorrowdUser] = ForeignKey(
        BorrowdUser,
        on_delete=CASCADE,
    )
    group: ForeignKey[BorrowdGroup] = ForeignKey(
        BorrowdGroup,
        on_delete=CASCADE,
    )
    is_moderator: BooleanField[bool, bool] = BooleanField(default=False)
    joined_at: DateTimeField[Never, Never] = DateTimeField(
        auto_now_add=True,
        help_text="The date and time at which the user joined the group.",
    )
    status: TextField[MembershipStatus, str] = TextField(
        choices=MembershipStatus.choices,
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
    trust_level: IntegerField[TrustLevel, int] = IntegerField(
        choices=TrustLevel,
        help_text="The User's selected level of Trust for the given Group.",
    )

    class Meta:
        constraints = [
            UniqueConstraint(fields=["user", "group"], name="unique_membership")
        ]
