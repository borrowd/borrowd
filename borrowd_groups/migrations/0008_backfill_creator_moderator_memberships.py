from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def backfill_group_creator_moderator_memberships(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """
    Backfill legacy group creator memberships so each group creator has an
    ACTIVE moderator membership.

    Older data allowed some creator memberships to be stored as PENDING in
    approval-required groups. Later permission checks began requiring ACTIVE
    status, which could lock creators out of their own groups.

    This migration repairs that historical data and re-saves the repaired
    membership so the current permission-sync signals restore any stale group
    and item permissions.

    See PR #408 for historical context:
    https://github.com/borrowd/borrowd/pull/408
    """
    from django.contrib.auth.models import Group

    from borrowd.models import TrustLevel
    from borrowd_groups.models import MembershipStatus

    BorrowdGroup = apps.get_model("borrowd_groups", "BorrowdGroup")
    Membership = apps.get_model("borrowd_groups", "Membership")

    all_existing_borrowd_groups = BorrowdGroup.objects.select_related(
        "created_by", "perms_group"
    )

    for existing_borrowd_group in all_existing_borrowd_groups.iterator():
        group_creator_user = existing_borrowd_group.created_by

        if existing_borrowd_group.perms_group is None:
            permissions_group_for_borrowd_group, _ = Group.objects.get_or_create(
                name=existing_borrowd_group.name
            )
            existing_borrowd_group.perms_group = permissions_group_for_borrowd_group
            existing_borrowd_group.save(update_fields=["perms_group"])

        group_creator_membership_record = Membership.objects.filter(
            user=group_creator_user,
            group=existing_borrowd_group,
        ).first()

        if group_creator_membership_record is None:
            Membership.objects.create(
                user=group_creator_user,
                group=existing_borrowd_group,
                trust_level=TrustLevel.HIGH,
                status=MembershipStatus.ACTIVE,
                is_moderator=True,
            )
            continue

        group_creator_membership_record.is_moderator = True
        group_creator_membership_record.status = MembershipStatus.ACTIVE
        group_creator_membership_record.save(update_fields=["is_moderator", "status"])


class Migration(migrations.Migration):
    dependencies = [
        ("borrowd_groups", "0007_alter_borrowdgroup_membership_requires_approval"),
    ]

    operations = [
        migrations.RunPython(
            backfill_group_creator_moderator_memberships,
            migrations.RunPython.noop,
        ),
    ]
