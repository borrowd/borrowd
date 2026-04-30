from typing import Never, Self

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import DO_NOTHING, SET_NULL, DateTimeField, ForeignKey
from django.templatetags.static import static
from guardian.mixins import GuardianUserMixin
from imagekit.models import ProcessedImageField
from imagekit.processors import ResizeToFit

from borrowd_groups.mixins import BorrowdGroupPermissionMixin


# No typing for django-guardian, so mypy doesn't like us subclassing.
class BorrowdUser(AbstractUser, BorrowdGroupPermissionMixin, GuardianUserMixin):  # type: ignore[misc]
    """
    Borrow'd's custom user model, extending Django's AbstractUser.

    This class is currently _empty_. We originally created it in
    order to specify a custom model for Group permissions, but we
    have since moved away from that approach.

    Still, keeping this custom user model in case we want to extend
    it later.
    """

    # Override the inherited fields to make them required
    first_name: models.CharField[str, str] = models.CharField(max_length=150)
    last_name: models.CharField[str, str] = models.CharField(max_length=150)
    created_by: ForeignKey[Self] = ForeignKey(
        "self",
        related_name="+",  # No reverse relation needed
        null=True,
        blank=False,
        help_text="The user who created the user.",
        on_delete=DO_NOTHING,
    )
    created_at: DateTimeField[Never, Never] = DateTimeField(
        auto_now_add=True,
        help_text="The date and time at which the user was created.",
    )
    updated_by: ForeignKey[Self] = ForeignKey(
        "self",
        related_name="+",  # No reverse relation needed
        null=True,
        blank=False,
        help_text="The last user who updated the user.",
        on_delete=DO_NOTHING,
    )
    updated_at: DateTimeField[Never, Never] = DateTimeField(
        auto_now=True,
        help_text="The date and time at which the user was last updated.",
    )
    deleted_at: DateTimeField[Never, Never] = DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text="Set when the record is soft-deleted. NULL means active.",
    )
    deleted_by: ForeignKey[Self] = ForeignKey(
        "self",
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="+",
        help_text="Who performed the soft-delete. NULL means active or unknown.",
    )

    # Hint for mypy (actual field created from reverse relation)
    profile: "Profile"


class Profile(models.Model):
    user: models.OneToOneField[BorrowdUser] = models.OneToOneField(
        BorrowdUser, on_delete=models.CASCADE
    )
    image = ProcessedImageField(
        upload_to="profile_pics/",
        processors=[ResizeToFit(1600, 1600)],
        format="JPEG",
        options={"quality": 75},
        null=True,
        blank=True,
    )
    bio: models.CharField[str, str] = models.CharField(
        max_length=200, blank=True, default=""
    )
    created_by: ForeignKey[BorrowdUser] = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The user who created the profile.",
        on_delete=DO_NOTHING,
    )
    created_at: DateTimeField[Never, Never] = DateTimeField(
        auto_now_add=True,
        help_text="The date and time at which the profile was created.",
    )
    updated_by: ForeignKey[BorrowdUser] = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The last user who updated the profile.",
        on_delete=DO_NOTHING,
    )
    updated_at: DateTimeField[Never, Never] = DateTimeField(
        auto_now=True,
        help_text="The date and time at which the profile was last updated.",
    )
    deleted_at: DateTimeField[Never, Never] = DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text="Set when the record is soft-deleted. NULL means active.",
    )
    deleted_by: ForeignKey[BorrowdUser] = ForeignKey(
        BorrowdUser,
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="+",
        help_text="Who performed the soft-delete. NULL means active or unknown.",
    )

    def full_name(self) -> str:
        return f"{self.user.first_name} {self.user.last_name}"

    def __str__(self) -> str:
        return f"Profile '{self.full_name()}' for User '{self.user}'"

    @property
    def profile_pic(self) -> str:
        pic: str = ""
        try:
            pic = self.image.url
        except Exception:
            pic = static("icons/account-circle.svg")
        return pic


class SearchTarget(models.TextChoices):
    ITEMS = "items", "Items"
    GROUPS = "groups", "Groups"


class SearchTerm(models.Model):
    """
    Store search terms entered by users so we can power UX features like
    "recent searches" and analyze search effectiveness.

    Append-only behavior:
    - Each search creates a row so we preserve full search history.
    """

    user: models.ForeignKey[BorrowdUser] = models.ForeignKey(
        "borrowd_users.BorrowdUser",
        on_delete=models.CASCADE,
        related_name="search_terms",
    )
    target: models.CharField[SearchTarget, str] = models.CharField(
        max_length=10,
        choices=SearchTarget.choices,
    )
    # Stored for UX (case/spacing as normalized by `record_search`).
    term_raw: models.CharField[str, str] = models.CharField(max_length=200)
    # Lowercased + whitespace collapsed for analytics queries.
    term_normalized: models.CharField[str, str] = models.CharField(max_length=200)

    created_at: models.DateTimeField[Never, Never] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        indexes = [
            # Fast "latest searches per user per target" queries.
            models.Index(fields=["user", "target", "-created_at"]),
            # Fast "latest searches by target" analytics queries.
            models.Index(fields=["target", "-created_at"]),
        ]
        ordering = ["-created_at"]

    @staticmethod
    def _normalize(term: str) -> tuple[str, str]:
        # Collapse whitespace so term analytics stay consistent.
        cleaned = " ".join(term.strip().split())
        normalized = cleaned.lower()
        return cleaned, normalized

    @classmethod
    def record_search(cls, user: BorrowdUser, target: SearchTarget, term: str) -> None:
        if not user.is_authenticated:
            return

        cleaned, normalized = cls._normalize(term)
        if not cleaned or not normalized:
            return

        # Enforce max length for DB fields.
        cleaned = cleaned[:200]
        normalized = normalized[:200]

        cls.objects.create(
            user=user,
            target=target,
            term_raw=cleaned,
            term_normalized=normalized,
        )
