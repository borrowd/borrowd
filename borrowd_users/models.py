from django.contrib.auth.models import AbstractUser
from django.db import models
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
    first_name: models.CharField[str, str] = models.CharField(
        max_length=50, null=False, blank=False
    )

    last_name: models.CharField[str, str] = models.CharField(
        max_length=50, null=False, blank=False
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
