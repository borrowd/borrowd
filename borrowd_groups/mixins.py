from django.contrib.auth.models import PermissionsMixin
from django.db.models import ManyToManyField


class BorrowdGroupPermissionMixin(PermissionsMixin):
    # As documented at:
    # https://django-guardian.readthedocs.io/en/latest/userguide/custom-group-model/
    # Note this is pre-release functionality, but... we need it!
    groups = ManyToManyField(
        "BorrowdGroup",
        verbose_name=("groups"),
        blank=True,
        help_text=(
            "The Groups this user belongs to. A user will get all permissions "
            "granted to each of their groups."
        ),
        related_name="user_set",
        related_query_name="user",
    )

    # No typing for django-guardian, so mypy doesn't like us subclassing.
    class Meta(PermissionsMixin.Meta):  # type: ignore[name-defined,misc]
        abstract = True
