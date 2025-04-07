from django.dispatch import receiver
from django.db.models import Model
from django.db.models.signals import post_save
from django.contrib.auth.models import User
from .models import Profile


# `**kwargs: str` is some dodgy nonsense to get around the fact that
# kwargs conceptually flies in the face of mypy style type checking.
@receiver(post_save, sender=User)
def user_postsave(sender: Model, instance: User, created: bool, **kwargs: str) -> None:
    """Add Profile whenever User is created."""
    if created:
        Profile.objects.create(user=instance)
