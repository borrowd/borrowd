from borrowd_items.models import Item
from borrowd_messaging.models import ChatThread


def hard_delete_threads_and_transactions(item: Item) -> None:
    """
    Destroy an item's chat threads and transactions for test teardown, in that
    order: messages reference threads with PROTECT and threads reference
    transactions the same way, so the graph comes apart from the bottom up.

    Threads are found by item, which is enough here because Transaction.item is
    PROTECT, so an item with transactions cannot be hard-deleted out from under
    them and leave a thread with a NULL item behind.

    A no-op when MESSAGING_ENABLED is off, since no threads exist to begin with.
    """
    for thread in ChatThread.objects.filter(item=item):
        thread.messages.all().delete()
        thread.delete()
    for tx in item.transactions.all():
        tx.delete()
