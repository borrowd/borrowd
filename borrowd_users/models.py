from django.contrib.auth.models import AbstractUser
from django.db import models
from django.templatetags.static import static
from guardian.mixins import GuardianUserMixin

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

    pass

    # Hint for mypy (actual field created from reverse relation)
    profile: "Profile"


class Profile(models.Model):
    user: models.OneToOneField[BorrowdUser] = models.OneToOneField(
        BorrowdUser, on_delete=models.CASCADE
    )
    image = models.ImageField(upload_to="profile_pics/", null=True, blank=True)
    display_name: models.CharField[str, str] = models.CharField(
        max_length=50, null=False, blank=False
    )

    def __str__(self) -> str:
        return str(f"Profile '{self.display_name}' for User '{self.user}'")

    @property
    def profile_pic(self) -> str:
        pic: str = ""
        try:
            pic = self.image.url
        except Exception:
            pic = static("icons/account-circle.svg")
        return pic
