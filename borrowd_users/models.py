from django.db import models
from django.contrib.auth.models import User
from django.templatetags.static import static


class Profile(models.Model):
    user: models.OneToOneField[User] = models.OneToOneField(
        User, on_delete=models.CASCADE
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
            pic = static("web/favicon.png")
        return pic
