from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver
from guardian.shortcuts import assign_perm

from borrowd_permissions.models import ChatThreadOLP

from .models import ChatThread


@receiver(post_save, sender=ChatThread)
def assign_chat_thread_permissions(
    sender: type[ChatThread], instance: ChatThread, created: bool, **kwargs: Any
) -> None:
    """
    Grant both parties view access when a thread is created.
    """
    if created:
        assign_perm(ChatThreadOLP.VIEW, instance.lender, instance)
        assign_perm(ChatThreadOLP.VIEW, instance.borrower, instance)
