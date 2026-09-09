from django.test import override_settings
from django.urls import reverse

from borrowd_messaging.models import ChatThread

from .base import MessagingTestCase


@override_settings(MESSAGING_ENABLED=True)
class ItemNameFilterTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("chat-thread-list")
        self.drill = self.make_thread()
        self.ladder = self.make_thread(item=self.make_item(name="Step Ladder"))
        self.client.force_login(self.borrower)

    def thread_ids(self, query: str = "") -> list[int]:
        response = self.client.get(f"{self.url}{query}")
        return [card.conversation.thread_id for card in response.context["cards"]]

    def test_matches_part_of_an_item_name(self) -> None:
        self.assertEqual(self.thread_ids("?item=ladd"), [self.ladder.pk])

    def test_ignores_capitalisation(self) -> None:
        self.assertEqual(self.thread_ids("?item=DRILL"), [self.drill.pk])

    def test_an_empty_filter_keeps_everything(self) -> None:
        self.assertEqual(
            set(self.thread_ids("?item=")), {self.drill.pk, self.ladder.pk}
        )

    def test_a_soft_deleted_item_still_matches_by_name(self) -> None:
        self.item.soft_delete(deleted_by=self.lender)

        self.assertEqual(
            self.thread_ids("?section=archived&item=drill"), [self.drill.pk]
        )

    def test_a_hard_deleted_item_has_no_name_left_to_match(self) -> None:
        self.item.delete()

        self.assertEqual(self.thread_ids("?section=archived&item=drill"), [])
        self.assertEqual(
            ChatThread.objects.filter(pk=self.drill.pk).values_list(
                "item_id", flat=True
            )[0],
            None,
        )

    def test_filtering_never_reaches_other_peoples_conversations(self) -> None:
        stranger = self.make_user("stranger")
        self.make_thread(item=self.make_item(name="Secret Drill"), borrower=stranger)

        self.assertEqual(self.thread_ids("?item=drill"), [self.drill.pk])

    def test_tabs_keep_the_filter_and_return_to_the_first_page(self) -> None:
        response = self.client.get(self.url, {"item": "drill", "page": "2"})

        archived = next(
            tab
            for tab in response.context["conversation_tabs"]
            if tab["name"] == "archived"
        )
        self.assertIn("item=drill", archived["url"])
        self.assertIn("section=archived", archived["url"])
        self.assertNotIn("page=", archived["url"])

    def test_paging_keeps_the_filter(self) -> None:
        for index in range(26):
            self.make_thread(item=self.make_item(name=f"Drill Bit {index}"))

        response = self.client.get(self.url, {"item": "drill"})

        self.assertEqual(len(response.context["cards"]), 25)
        self.assertContains(response, "item=drill")

    def test_applying_a_filter_keeps_the_open_tab(self) -> None:
        response = self.client.get(self.url, {"section": "archived"})

        self.assertContains(response, 'name="section" value="archived"')
