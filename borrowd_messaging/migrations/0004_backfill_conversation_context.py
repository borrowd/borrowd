from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.db.models import Q

# Keep the historical value local so future enum changes cannot alter this migration.
_MEMBERSHIP_STATUS_ACTIVE = "ACTIVE"


def backfill_conversation_context(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Backfill only conversation context that current records prove."""
    BorrowdGroup = apps.get_model("borrowd_groups", "BorrowdGroup")
    Item = apps.get_model("borrowd_items", "Item")
    Membership = apps.get_model("borrowd_groups", "Membership")
    ChatThread = apps.get_model("borrowd_messaging", "ChatThread")
    database = schema_editor.connection.alias

    threads = (
        ChatThread.objects.using(database)
        .filter(item__isnull=False)
        .filter(
            Q(listing_type__isnull=True)
            | Q(
                conversation_group__isnull=True,
                conversation_group_source_id__isnull=True,
                conversation_group_name__isnull=True,
            )
        )
        .select_related("item")
    )

    for thread in threads.iterator(chunk_size=500):
        item = thread.item
        if item.owner_id != thread.lender_id:
            continue

        updates = {}
        if thread.listing_type is None:
            updates["listing_type"] = item.listing_type

        has_no_group_context = (
            thread.conversation_group_id is None
            and thread.conversation_group_source_id is None
            and thread.conversation_group_name is None
        )
        if has_no_group_context:
            owner_group_ids = (
                Membership.objects.using(database)
                .filter(
                    user_id=item.owner_id,
                    status=_MEMBERSHIP_STATUS_ACTIVE,
                    joined_at__lte=thread.created_at,
                )
                .values_list("group_id", flat=True)
            )
            borrower_group_ids = (
                Membership.objects.using(database)
                .filter(
                    user_id=thread.borrower_id,
                    status=_MEMBERSHIP_STATUS_ACTIVE,
                    joined_at__lte=thread.created_at,
                )
                .values_list("group_id", flat=True)
            )
            eligible_groups = (
                BorrowdGroup.objects.using(database)
                .filter(
                    pk__in=owner_group_ids,
                    deleted_at__isnull=True,
                    perms_group__isnull=False,
                )
                .filter(pk__in=borrower_group_ids)
            )
            if not item.share_with_all_groups:
                shared_group_ids = (
                    Item.shared_with_groups.through.objects.using(database)
                    .filter(item_id=item.pk)
                    .values_list("borrowdgroup_id", flat=True)
                )
                eligible_groups = eligible_groups.filter(pk__in=shared_group_ids)

            candidates = list(eligible_groups.order_by("pk")[:2])
            if len(candidates) == 1:
                conversation_group = candidates[0]
                updates.update(
                    conversation_group_id=conversation_group.pk,
                    conversation_group_source_id=conversation_group.pk,
                    conversation_group_name=conversation_group.name,
                )

        if updates:
            ChatThread.objects.using(database).filter(pk=thread.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("borrowd_messaging", "0003_chatthread_conversation_group_and_more"),
    ]

    operations = [
        migrations.RunPython(
            backfill_conversation_context,
            migrations.RunPython.noop,
        ),
    ]
