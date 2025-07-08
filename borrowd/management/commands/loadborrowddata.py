from django.core.management.commands.loaddata import Command as BaseLoadDataCommand
from django.db.models.signals import (
    pre_init,
    post_init,
    pre_save,
    post_save,
    pre_delete,
    post_delete,
)

class Command(BaseLoadDataCommand):
    def loaddata(self, fixture_labels):
        for signal in [
            pre_init,
            post_init,
            pre_save,
            post_save,
            pre_delete,
            post_delete,
        ]:
            signal.receivers = []

        super().loaddata(fixture_labels)