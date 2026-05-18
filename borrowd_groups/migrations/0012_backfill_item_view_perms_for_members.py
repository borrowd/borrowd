from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

# Inlining rather than importing constants because src could change.
# values come from:
#   - borrowd_permissions/models.py -> ItemOLP.VIEW
#   - borrowd_groups/models.py      -> MembershipStatus.ACTIVE
# https://docs.djangoproject.com/en/5.2/topics/migrations/#historical-models
_ITEM_VIEW_PERM = "view_this_item"
_MEMBERSHIP_STATUS_ACTIVE = "ACTIVE"


def backfill_item_view_perms_for_members(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """
    Repair item visibility for items owned by non-creator group members.

    Issue: See PR #467

    fix: for every ACTIVE Membership, assign ItemOLP.VIEW to
    that group's perms_group for each item the member owns whose
    trust_level_required is at or below their trust_level.
    """
    # We need the live auth Group class because guardian's
    # `get_identity` does `isinstance(group, AuthGroup)` against the live class;
    # the historical Group from apps.get_model would fail the check. See:
    # https://github.com/django-guardian/django-guardian/blob/main/guardian/utils.py#L92
    # https://django-guardian.readthedocs.io/en/stable/api/utils/

    from django.contrib.auth.models import Group as AuthGroup
    from guardian.shortcuts import assign_perm

    # historical model classes below
    # https://docs.djangoproject.com/en/5.2/topics/migrations/#data-migrations
    Item = apps.get_model("borrowd_items", "Item")
    Membership = apps.get_model("borrowd_groups", "Membership")

    # fetch all 'active' members of a group
    memberships = Membership.objects.filter(
        status=_MEMBERSHIP_STATUS_ACTIVE,
    ).select_related("group", "user")

    # Iterator is used to skip queryset caching and avoid loading all memberships into memory
    # See: https://docs.djangoproject.com/en/5.2/ref/models/querysets/#iterator
    for membership in memberships.iterator():
        perms_group_id = membership.group.perms_group_id
        if perms_group_id is None:
            # No auth Group attached to the BorrowdGroup, nothing to grant perms on.
            continue

        # Fetch the live AuthGroup for guardian's isinstance check
        perms_group = AuthGroup.objects.get(pk=perms_group_id)

        # fetch all items owned by the member that they should have view perms for
        items = Item.objects.filter(
            owner=membership.user,
            trust_level_required__lte=membership.trust_level,
        )

        # Assign view perms for each item for that group
        # assign_perm with a QuerySet routes to bulk_assign_perm
        # guardian's bulk_assign_perm checks each row before inserting.
        # https://github.com/django-guardian/django-guardian/blob/main/guardian/managers.py
        # https://django-guardian.readthedocs.io/en/stable/userguide/assign/
        assign_perm(_ITEM_VIEW_PERM, perms_group, items)


class Migration(migrations.Migration):
    dependencies = [
        # depends on Item.trust_level_required and owner
        (
            "borrowd_items",
            "0018_audit_3",
        ),
        # depends on Membership and BorrowdGroup.perms_group_id
        (
            "borrowd_groups",
            "0011_merge_20260414_1406",
        ),
        # We read auth_group via live AuthGroup; assign_perm also writes auth_permission FKs.
        (
            "auth",
            "0012_alter_user_first_name_max_length",
        ),
    ]

    operations = [
        migrations.RunPython(
            backfill_item_view_perms_for_members,
            migrations.RunPython.noop,
        ),
    ]
