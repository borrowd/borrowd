from borrowd_items.models import Item
from borrowd_messaging.models import ChatThread


def hard_delete_transactions_and_threads(item: Item) -> None:
    """
    Destroy an item's transactions for test teardown. Chat threads reference
    transactions with PROTECT, and messages reference threads the same way,
    so the graph has to come apart from the bottom up.
    """
    for thread in ChatThread.objects.filter(item=item):
        thread.messages.all().delete()
        thread.delete()
    for tx in item.transactions.all():
        tx.delete()
