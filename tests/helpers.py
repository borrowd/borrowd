from borrowd_items.models import Item
from borrowd_messaging.models import ChatThread


def hard_delete_threads_and_transactions(item: Item) -> None:
    """
    Destroy an item's chats and transactions in test teardown.

    Since we have messages and threads set to PROTECT, we have to delete from
    the bottom (messages) up.
    """
    # no-op when no chats (e.g. MESSAGING_ENABLED == false)
    for thread in ChatThread.objects.filter(item=item):
        thread.messages.all().delete()
        thread.delete()
    # always runs
    for tx in item.transactions.all():
        tx.delete()
