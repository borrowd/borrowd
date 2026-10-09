from django.db.models import (
    CASCADE,
    CharField,
    DateTimeField,
    ForeignKey,
    Model,
    PositiveIntegerField,
    SlugField,
    UniqueConstraint,
)

from borrowd_users.models import BorrowdUser


class Badge(Model):
    """
    A badge a user can earn, shown on their profile as a gamification
    layer. Badges are seeded via the `badges/badges` fixture rather than
    created through the app; each badge's earning condition is implemented
    separately as that badge is wired up.

    `slug` doubles as the static asset name: a badge's icon lives at
    `static/badges/<slug>.png` (earned) and `static/badges/<slug>-gray.png`
    (not yet earned).
    """

    slug = SlugField(max_length=50, unique=True)
    name = CharField(max_length=50)
    description = CharField(max_length=200, blank=True, default="")
    display_order = PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.name

    class Meta:
        ordering = ["display_order", "name"]


class UserBadge(Model):
    """Records that a user has earned a badge."""

    user = ForeignKey(BorrowdUser, on_delete=CASCADE, related_name="earned_badges")
    badge = ForeignKey(Badge, on_delete=CASCADE, related_name="earned_by")
    earned_at = DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user} earned {self.badge}"

    class Meta:
        constraints = [
            UniqueConstraint(fields=["user", "badge"], name="unique_user_badge"),
        ]
