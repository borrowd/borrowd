# Generated by Django 5.2 on 2025-05-03 08:21

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("borrowd_items", "0002_item_trust_level_required"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="item",
            options={
                "permissions": [
                    ("view_this_item", "Can view this item"),
                    ("edit_this_item", "Can edit this item"),
                    ("delete_this_item", "Can delete this item"),
                    ("borrow_this_item", "Can borrow this item"),
                ]
            },
        ),
    ]
