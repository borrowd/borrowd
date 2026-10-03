"""Lifecycle action forms send the revision and key the command service checks."""

from uuid import uuid4

from django.contrib.messages import get_messages
from django.urls import reverse
from guardian.shortcuts import assign_perm

from borrowd_items.models import ItemAction, Transaction
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
