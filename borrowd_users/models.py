from typing import Never

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.templatetags.static import static
from guardian.mixins import GuardianUserMixin
from imagekit.models import ProcessedImageField
from imagekit.processors import ResizeToFit

from borrowd_groups.mixins import BorrowdGroupPermissionMixin

from django.utils import timezone


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
        max_length=120, blank=True, default=""
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

    Dedupe behavior:
    - A user + target (items/groups) + normalized term creates at most one
      row, but we update `last_searched_at` on repeat searches.
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
    # Used for dedupe; lowercased + whitespace collapsed.
    term_normalized: models.CharField[str, str] = models.CharField(max_length=200)

    created_at: models.DateTimeField[Never, Never] = models.DateTimeField(
        auto_now_add=True,
    )
    last_searched_at: models.DateTimeField[Never, Never] = models.DateTimeField(
        default=timezone.now,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "target", "term_normalized"],
                name="unique_search_term_per_user_target",
            )
        ]
        indexes = [
            # Fast "latest searches per user per target" queries.
            models.Index(fields=["user", "target", "-last_searched_at"]),
            # Fast "latest searches by target" analytics queries.
            models.Index(fields=["target", "-last_searched_at"]),
        ]
        ordering = ["-last_searched_at"]

    @staticmethod
    def _normalize(term: str) -> tuple[str, str]:
        # Collapse whitespace so "usb  charger" and "usb charger" dedupe.
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

        # Enforce max length for DB fields while keeping dedupe consistent.
        cleaned = cleaned[:200]
        normalized = normalized[:200]

        obj, created = cls.objects.get_or_create(
            user=user,
            target=target,
            term_normalized=normalized,
            defaults={"term_raw": cleaned},
        )

        if not created:
            # Keep stored term consistent with our normalization strategy.
            obj.term_raw = cleaned

        obj.last_searched_at = timezone.now()
        obj.save(update_fields=["term_raw", "last_searched_at"])
