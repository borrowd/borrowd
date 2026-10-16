from django.db import migrations


def backfill_join_method(apps, schema_editor):
    """
    Classify each existing membership by comparing its user against its
    group's creator -- the only two ways a membership can have begun
    before this field existed. Left NULL if the group row (and so its
    creator) can't be found.
    """
    Membership = apps.get_model("borrowd_groups", "Membership")

    rows = Membership.objects.select_related("group").iterator()
    creators, joiners = [], []
    for membership in rows:
        if membership.group_id is None:
            continue
        if membership.user_id == membership.group.created_by_id:
            creators.append(membership.pk)
        else:
            joiners.append(membership.pk)

    Membership.objects.filter(pk__in=creators).update(join_method="GROUP_CREATOR")
    Membership.objects.filter(pk__in=joiners).update(join_method="JOINED_GROUP")


def clear_join_method(apps, schema_editor):
    Membership = apps.get_model("borrowd_groups", "Membership")
    Membership.objects.update(join_method=None)


class Migration(migrations.Migration):
    dependencies = [
        ("borrowd_groups", "0015_membership_join_method_and_departures"),
    ]

    operations = [
        migrations.RunPython(backfill_join_method, clear_join_method),
    ]
