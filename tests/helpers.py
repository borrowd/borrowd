from borrowd_items.models import Item
from borrowd_messaging.models import ChatThread


def hard_delete_threads_and_transactions(item: Item) -> None:
    """
    Destroy an item's chats and transactions in test teardown.

    Order matters. Messages point at chats, and chats point at transactions.
    Both links are PROTECT, so nothing can be deleted while something still
    points at it. Start at the bottom.

    Does nothing if the item has no chats, which is the case whenever
    MESSAGING_ENABLED is off.
    """
    for thread in ChatThread.objects.filter(item=item):
        thread.messages.all().delete()
        thread.delete()
    for tx in item.transactions.all():
        tx.delete()
