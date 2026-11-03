from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

import borrowd_groups.models


def give_each_group_its_own_code(
    apps: Apps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    # A callable default on AddField is evaluated once, so every existing
    # row would otherwise share one code.
    BorrowdGroup = apps.get_model("borrowd_groups", "BorrowdGroup")
    for group in BorrowdGroup.objects.only("pk"):
        group.invite_code = borrowd_groups.models.new_invite_code()
        group.save(update_fields=["invite_code"])


class Migration(migrations.Migration):
    dependencies = [
        ("borrowd_groups", "0016_backfill_membership_join_method"),
    ]

    operations = [
        migrations.AddField(
            model_name="borrowdgroup",
            name="members_can_share_invite_link",
            field=models.BooleanField(
                default=True,
                help_text="Group members can share invitation links",
            ),
        ),
        migrations.AddField(
            model_name="borrowdgroup",
            name="invite_code",
            field=models.CharField(max_length=16, null=True),
        ),
        migrations.RunPython(give_each_group_its_own_code, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="borrowdgroup",
            name="invite_code",
            field=models.CharField(
                default=borrowd_groups.models.new_invite_code,
                help_text="Signed into the group's invite links. Resetting it invalidates every existing link and printed poster.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="borrowdgroup",
            name="invite_code_reset_at",
            field=models.DateTimeField(
                blank=True,
                default=None,
                help_text="When a moderator last reset the invite link. NULL means never.",
                null=True,
            ),
        ),
    ]
