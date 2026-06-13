from django.contrib.auth.models import Group, PermissionsMixin
from django.db.models import ManyToManyField


class BorrowdGroupPermissionMixin(PermissionsMixin):
    # As documented at:
    # https://django-guardian.readthedocs.io/en/latest/userguide/custom-group-model/
    # Note this is pre-release functionality, but... we need it!
    #
    # NOTE: this field is currently inert: AbstractUser comes first in
    # BorrowdUser's MRO, so its auth.Group-targeting field wins (see the
    # borrowd_users 0001 migration). The annotation reflects that runtime
    # reality, which call sites like user.groups.add(perms_group) rely on.
    groups: ManyToManyField[Group, Group] = ManyToManyField(
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

    class Meta(PermissionsMixin.Meta):
        abstract = True
