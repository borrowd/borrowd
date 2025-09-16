import random
import string
import uuid
from typing import Any, Never

from django.conf import settings
from django.db import models
from django.db.models import (
    CharField,
    DateTimeField,
    ForeignKey,
    PositiveIntegerField,
    UUIDField,
)
from django.forms import ValidationError


class BetaCode(models.Model):
    name: CharField[str, str] = CharField(
        unique=True, max_length=255, help_text="A descriptive name for this beta code."
    )
    num_uses: PositiveIntegerField[int, int] = PositiveIntegerField(
        default=10, help_text="Number of times this code can be used."
    )
    code: CharField[str, str] = CharField(
        max_length=7,
        unique=True,
        help_text="Auto-generated 7-character alphanumeric code.",
    )
    created_by: ForeignKey[Any] = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=False,
        blank=False,
        related_name="created_beta_codes",
        help_text="Admin user who created this beta code.",
    )
    updated_by: ForeignKey[Any] = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="updated_beta_codes",
        help_text="Admin user who last updated this beta code.",
    )
    created_at: DateTimeField[Never, Never] = DateTimeField(auto_now_add=True)
    updated_at: DateTimeField[Never, Never] = DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name} - Created by: {self.created_by} - Code: {self.code}"

    @staticmethod
    def generate_code() -> str:
        length = 7
        chars = string.ascii_uppercase + string.digits
        return "".join(random.choice(chars) for _ in range(length))


class BetaSignup(models.Model):
    beta_code: ForeignKey[BetaCode] = models.ForeignKey(
        BetaCode, related_name="signups", on_delete=models.CASCADE
    )
    token: UUIDField[str, str] = UUIDField(
        default=uuid.uuid4, editable=False, unique=True
    )
    submitted_at: DateTimeField[Never, Never] = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Code: {self.beta_code.code} - Token: {self.token}"  # type: ignore[attr-defined]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.beta_code.signups.count() >= self.beta_code.num_uses:  # type: ignore[attr-defined]
            raise ValidationError("Beta code usage limit reached.")
        super().save(*args, **kwargs)
