"""Lifecycle action forms send the revision and key the command service checks."""

from uuid import uuid4

from django.contrib.messages import get_messages
from django.urls import reverse
from guardian.shortcuts import assign_perm, remove_perm

from borrowd_items.models import (
    ItemAction,
    ItemCommandRecord,
    Transaction,
    TransactionStatus,
)
from borrowd_items.tests.test_item_commands import CommandTestCase
from borrowd_permissions.models import ItemOLP


class ActionFormTests(CommandTestCase):
    def setUp(self) -> None:
        super().setUp()
        assign_perm(ItemOLP.VIEW, self.alice, self.item)
        self.client.force_login(self.alice)
        self.url = reverse("item-borrow", args=[self.item.pk])

    def post(self, **fields: str) -> list[str]:
        response = self.client.post(
            self.url, {"action": ItemAction.REQUEST_ITEM, **fields}
        )
        self.assertEqual(response.status_code, 302)
        return [str(message) for message in get_messages(response.wsgi_request)]

    def test_forms_carry_the_revision_and_a_key(self) -> None:
        response = self.client.get(reverse("item-detail", args=[self.item.pk]))
        self.assertContains(response, f'name="revision" value="{self.item.revision}"')
        self.assertContains(response, 'name="command_key"')

    def test_a_stale_page_is_refused_with_a_message(self) -> None:
        sent = self.post(revision="7", command_key=str(uuid4()))

        self.assertIn("changed since you loaded the page", sent[0])
        self.assertFalse(Transaction.objects.filter(item=self.item).exists())

    def test_a_double_submit_requests_once(self) -> None:
        fields = {"revision": "0", "command_key": str(uuid4())}
        self.post(**fields)
        self.post(**fields)
        self.assertEqual(Transaction.objects.filter(item=self.item).count(), 1)

    def test_a_malformed_key_is_a_bad_request(self) -> None:
        response = self.client.post(
            self.url, {"action": ItemAction.REQUEST_ITEM, "command_key": "nope"}
        )
        self.assertEqual(response.status_code, 400)

    def test_a_key_without_a_revision_is_a_bad_request(self) -> None:
        response = self.client.post(
            self.url, {"action": ItemAction.REQUEST_ITEM, "command_key": str(uuid4())}
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Transaction.objects.filter(item=self.item).exists())

    def test_a_legacy_form_without_either_field_still_works(self) -> None:
        self.post()
        self.assertEqual(Transaction.objects.filter(item=self.item).count(), 1)

    def test_a_retry_after_visibility_is_removed_still_succeeds(self) -> None:
        fields = {"revision": "0", "command_key": str(uuid4())}
        self.post(**fields)
        remove_perm(ItemOLP.VIEW, self.alice, self.item)
        self.post(**fields)
        self.assertEqual(ItemCommandRecord.objects.count(), 1)
        response = self.client.post(self.url, {"action": ItemAction.CANCEL_REQUEST})
        self.assertEqual(response.status_code, 404)

    def test_another_actor_cannot_replay_the_key(self) -> None:
        fields = {"revision": "0", "command_key": str(uuid4())}
        self.post(**fields)
        self.client.force_login(self.bob)
        response = self.client.post(
            self.url, {"action": ItemAction.REQUEST_ITEM, **fields}
        )
        self.assertFalse(ItemCommandRecord.objects.filter(actor=self.bob).exists())
        self.assertEqual(response.status_code, 404)

    def test_a_retry_after_resolving_a_lost_item_still_succeeds(self) -> None:
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.alice,
            status=TransactionStatus.DISPUTED,
            created_by=self.alice,
            updated_by=self.owner,
        )
        self.client.force_login(self.owner)
        fields = {
            "action": ItemAction.RESOLVE_DISPUTE_NOT_RETURNED,
            "revision": str(self.revision()),
            "command_key": str(uuid4()),
        }
        self.assertEqual(self.client.post(self.url, fields).status_code, 302)
        self.item.refresh_from_db()
        self.assertIsNotNone(self.item.deleted_at)
        self.assertEqual(self.client.post(self.url, fields).status_code, 302)
        self.assertEqual(ItemCommandRecord.objects.count(), 1)
        fields["command_key"] = str(uuid4())
        fields["revision"] = str(self.revision())
        self.assertEqual(self.client.post(self.url, fields).status_code, 404)

    def test_an_unknown_action_without_access_is_not_found(self) -> None:
        remove_perm(ItemOLP.VIEW, self.alice, self.item)
        response = self.client.post(self.url, {"action": "unknown"})
        self.assertEqual(response.status_code, 404)

    def test_a_mismatched_retry_without_access_is_not_found(self) -> None:
        fields = {"revision": "0", "command_key": str(uuid4())}
        self.post(**fields)
        remove_perm(ItemOLP.VIEW, self.alice, self.item)
        response = self.client.post(
            self.url, {"action": ItemAction.CANCEL_REQUEST, **fields}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(ItemCommandRecord.objects.count(), 1)
