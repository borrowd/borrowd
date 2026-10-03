"""
Lifecycle actions sent by a client. A command says what the client was
showing (the item's revision, and the transaction it meant) and carries a key,
so a stale page is refused and a retry after a lost response is answered
instead of run twice.
"""

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from django.db import transaction

from borrowd_users.models import BorrowdUser

from .exceptions import CommandKeyReused, StaleItemCommand
from .models import Item, ItemAction, ItemCommandRecord, TransactionStatus


@dataclass(frozen=True)
class ItemCommand:
    actor: BorrowdUser
    action: ItemAction
    item_id: int
    # What the client was showing. None skips that check, for clients that
    # don't send it yet.
    expected_revision: int | None = None
    transaction_id: int | None = None
    key: UUID | None = None

    def fingerprint(self) -> str:
        """Everything a retry of this command has to repeat exactly."""
        asked = (
            self.action.value,
            self.item_id,
            self.expected_revision,
            self.transaction_id,
        )
        return sha256(repr(asked).encode()).hexdigest()


@dataclass(frozen=True)
class CommandResult:
    item_id: int
    revision: int
    transaction_id: int | None
    transaction_status: TransactionStatus | None
    replayed: bool = False


def run_item_command(
    command: ItemCommand, *, before: Callable[[Item], None] | None = None
) -> CommandResult:
    """
    Run one lifecycle action under the same locks as Item.process_action.
    `before` runs under those locks just ahead of the action, for work that
    has to commit or roll back with it.
    """
    with transaction.atomic():
        item = Item.lock_for_action(command.actor, command.item_id)
        # A retry is answered before anything else is checked: the state it
        # was decided on has moved on, because of the command itself.
        if command.key is not None:
            recorded = ItemCommandRecord.objects.filter(
                actor=command.actor, key=command.key
            ).first()
            if recorded is not None:
                return _replay(recorded, command)

        _check_what_the_client_saw(item, command)
        if before is not None:
            before(item)
        tx = item._process_action_locked(command.actor, command.action)

        result = CommandResult(
            item_id=item.pk,
            revision=Item.all_objects.values_list("revision", flat=True).get(
                pk=item.pk
            ),
            transaction_id=tx.pk if tx is not None else None,
            transaction_status=(
                TransactionStatus(tx.status) if tx is not None else None
            ),
        )
        if command.key is not None:
            ItemCommandRecord.objects.create(
                actor=command.actor,
                key=command.key,
                fingerprint=command.fingerprint(),
                action=command.action,
                item=item,
                transaction=tx,
                transaction_status=result.transaction_status,
                revision=result.revision,
            )
        return result


def _check_what_the_client_saw(item: Item, command: ItemCommand) -> None:
    if (
        command.expected_revision is not None
        and command.expected_revision != item.revision
    ):
        raise StaleItemCommand(
            f"Item {item.pk} is at revision {item.revision}, "
            f"not {command.expected_revision}.",
            current_revision=item.revision,
        )
    if command.transaction_id is not None:
        current = item.get_current_transaction_for_user(command.actor)
        if current is None or current.pk != command.transaction_id:
            raise StaleItemCommand(
                f"Transaction {command.transaction_id} is not the current one "
                f"on item {item.pk}.",
                current_revision=item.revision,
            )


def _replay(recorded: ItemCommandRecord, command: ItemCommand) -> CommandResult:
    if recorded.fingerprint != command.fingerprint():
        raise CommandKeyReused(
            f"Key {command.key} was already used for a different command."
        )
    return CommandResult(
        item_id=recorded.item_id,
        revision=recorded.revision,
        transaction_id=recorded.transaction_id,
        transaction_status=(
            TransactionStatus(recorded.transaction_status)
            if recorded.transaction_status is not None
            else None
        ),
        replayed=True,
    )
