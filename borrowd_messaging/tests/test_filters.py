from django.test import override_settings
from django.urls import reverse

from borrowd_messaging.models import ChatThread, Message
from borrowd_messaging.read_state import mark_thread_read
from borrowd_messaging.services import MessagingService

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
        return [card.summary.thread_id for card in response.context["cards"]]

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


@override_settings(MESSAGING_ENABLED=True)
class PersonFilterTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("chat-thread-list")
        self.lender.first_name, self.lender.last_name = "Ada", "Lovelace"
        self.lender.save()
        self.borrower.first_name, self.borrower.last_name = "Grace", "Hopper"
        self.borrower.save()
        self.with_ada = self.make_thread()

        self.other = self.make_user("other")
        self.other.first_name, self.other.last_name = "Alan", "Turing"
        self.other.save()
        self.with_alan = self.make_thread(
            item=self.make_item(name="Ladder", owner=self.other), lender=self.other
        )
        self.client.force_login(self.borrower)

    def thread_ids(self, query: str = "") -> list[int]:
        response = self.client.get(f"{self.url}{query}")
        return [card.summary.thread_id for card in response.context["cards"]]

    def test_matches_a_first_name(self) -> None:
        self.assertEqual(self.thread_ids("?person=ada"), [self.with_ada.pk])

    def test_matches_a_last_name(self) -> None:
        self.assertEqual(self.thread_ids("?person=turing"), [self.with_alan.pk])

    def test_matches_a_full_name(self) -> None:
        self.assertEqual(self.thread_ids("?person=ada+lovelace"), [self.with_ada.pk])

    def test_word_order_does_not_matter(self) -> None:
        self.assertEqual(self.thread_ids("?person=lovelace+ada"), [self.with_ada.pk])

    def test_every_word_has_to_match(self) -> None:
        self.assertEqual(self.thread_ids("?person=ada+turing"), [])

    def test_ignores_capitalisation(self) -> None:
        self.assertEqual(self.thread_ids("?person=LOVELACE"), [self.with_ada.pk])

    def test_never_matches_the_viewer_themselves(self) -> None:
        self.assertEqual(self.thread_ids("?person=grace"), [])
        self.assertEqual(self.thread_ids("?person=hopper"), [])

    def test_matches_the_borrower_when_the_viewer_is_the_lender(self) -> None:
        self.client.force_login(self.lender)

        self.assertEqual(self.thread_ids("?person=hopper"), [self.with_ada.pk])

    def test_stacks_with_the_item_filter(self) -> None:
        self.assertEqual(self.thread_ids("?person=ada&item=drill"), [self.with_ada.pk])
        self.assertEqual(self.thread_ids("?person=ada&item=ladder"), [])


@override_settings(MESSAGING_ENABLED=True)
class UnreadFilterTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("chat-thread-list")
        self.unread = self.make_thread()
        Message.objects.create(
            thread=self.unread, sender=self.lender, body="Free Saturday?"
        )
        self.read = self.make_thread(item=self.make_item(name="Ladder"))
        seen = Message.objects.create(
            thread=self.read, sender=self.lender, body="Ladder is free too."
        )
        mark_thread_read(self.read, self.borrower, through_message_id=seen.pk)
        self.client.force_login(self.borrower)

    def thread_ids(self, query: str = "") -> list[int]:
        response = self.client.get(f"{self.url}{query}")
        return [card.summary.thread_id for card in response.context["cards"]]

    def test_keeps_only_unacknowledged_conversations(self) -> None:
        self.assertEqual(self.thread_ids("?unread=on"), [self.unread.pk])

    def test_leaving_it_off_keeps_everything(self) -> None:
        self.assertEqual(set(self.thread_ids()), {self.unread.pk, self.read.pk})

    def test_your_own_messages_do_not_make_a_conversation_unread(self) -> None:
        mine = self.make_thread(item=self.make_item(name="Saw"))
        Message.objects.create(thread=mine, sender=self.borrower, body="Hello?")

        self.assertNotIn(mine.pk, self.thread_ids("?unread=on"))

    def test_an_archived_notice_still_counts_as_unread(self) -> None:
        closing = self.make_thread(item=self.make_item(name="Tent"))
        MessagingService.close_prerequest_thread(closing, self.lender)

        self.assertEqual(self.thread_ids("?section=archived&unread=on"), [closing.pk])

    def test_stacks_with_the_item_filter(self) -> None:
        self.assertEqual(self.thread_ids("?unread=on&item=drill"), [self.unread.pk])
        self.assertEqual(self.thread_ids("?unread=on&item=ladder"), [])


@override_settings(MESSAGING_ENABLED=True)
class ClearFiltersTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("chat-thread-list")
        self.make_thread()
        self.client.force_login(self.borrower)

    def test_no_clear_control_until_something_is_filtered(self) -> None:
        self.assertNotContains(self.client.get(self.url), "Clear filters")

    def test_an_applied_filter_offers_a_way_out(self) -> None:
        response = self.client.get(self.url, {"item": "drill"})

        self.assertContains(response, "Clear filters")
        self.assertEqual(response.context["clear_filters_url"], "?section=active")

    def test_an_empty_filter_value_is_not_treated_as_filtering(self) -> None:
        response = self.client.get(self.url, {"item": "", "person": ""})

        self.assertFalse(response.context["filters_applied"])
        self.assertNotContains(response, "Clear filters")

    def test_clearing_keeps_the_open_tab(self) -> None:
        response = self.client.get(self.url, {"section": "archived", "item": "drill"})

        self.assertEqual(response.context["clear_filters_url"], "?section=archived")

    def test_the_unread_checkbox_counts_as_a_filter(self) -> None:
        self.assertContains(
            self.client.get(self.url, {"unread": "on"}), "Clear filters"
        )


@override_settings(MESSAGING_ENABLED=True)
class FilteredEmptyStateTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("chat-thread-list")
        self.client.force_login(self.borrower)

    def test_filters_that_match_nothing_say_so(self) -> None:
        self.make_thread()

        response = self.client.get(self.url, {"item": "nothing-like-this"})

        self.assertContains(response, "No conversations match your filters.")
        self.assertNotContains(response, "No active conversations.")

    def test_an_unfiltered_empty_tab_still_names_the_tab(self) -> None:
        self.make_thread()

        response = self.client.get(self.url, {"section": "archived"})

        self.assertContains(response, "No archived conversations.")
        self.assertNotContains(response, "No conversations match your filters.")

    def test_someone_with_nothing_at_all_is_not_told_about_filters(self) -> None:
        response = self.client.get(self.url, {"item": "drill"})

        self.assertContains(response, "no conversations yet")
        self.assertNotContains(response, "No conversations match your filters.")

    def test_the_filters_stay_on_screen_when_nothing_matches(self) -> None:
        self.make_thread()

        response = self.client.get(self.url, {"item": "nothing-like-this"})

        self.assertContains(response, "Clear filters")
        self.assertContains(response, 'value="nothing-like-this"')
