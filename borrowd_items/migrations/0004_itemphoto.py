# Generated by Django 5.2 on 2025-05-16 00:25

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("borrowd_items", "0003_alter_item_options"),
    ]

    operations = [
        migrations.CreateModel(
            name="ItemPhoto",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("image", models.ImageField(upload_to="items")),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="photos",
                        to="borrowd_items.item",
                    ),
                ),
            ],
        ),
    ]
