from django.db import migrations


def backfill_status_history(apps, schema_editor):
    """
    One row per existing Transaction, standing in for its creation. These
    rows aren't timed transitions -- changed_at is the transaction's
    updated_at, not when it was actually created -- so reports must treat
    them as current state only.
    """
    Transaction = apps.get_model("borrowd_items", "Transaction")
    TransactionStatusChange = apps.get_model("borrowd_items", "TransactionStatusChange")

    rows = (
        TransactionStatusChange(
            transaction_id=txn.pk,
            from_status=None,
            to_status=txn.status,
            action=None,
            actor=None,
            resolution_reason=txn.resolution_reason,
            changed_at=txn.updated_at,
            backfilled=True,
        )
        for txn in Transaction.objects.all().iterator()
    )
    TransactionStatusChange.objects.bulk_create(rows, batch_size=1000)


def remove_backfilled_history(apps, schema_editor):
    TransactionStatusChange = apps.get_model("borrowd_items", "TransactionStatusChange")
    TransactionStatusChange.objects.filter(backfilled=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("borrowd_items", "0026_transaction_status_history"),
    ]

    operations = [
        migrations.RunPython(backfill_status_history, remove_backfilled_history),
    ]
