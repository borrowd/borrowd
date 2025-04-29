from django.contrib.auth.models import AbstractUser
from django.db import models
from django.templatetags.static import static


class BorrowdUser(AbstractUser):
    pass


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
            pic = static("favicon.png")
        return pic
