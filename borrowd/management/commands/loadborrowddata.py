from typing import Sequence

from django.core.management.commands.loaddata import Command as BaseLoadDataCommand
from django.db.models.signals import (
    post_delete,
    post_init,
    post_save,
    pre_delete,
    pre_init,
    pre_save,
)


class Command(BaseLoadDataCommand):
    def loaddata(self, fixture_labels: Sequence[str]) -> None:
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
