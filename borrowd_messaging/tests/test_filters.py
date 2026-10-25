import html
import re

from django.http import QueryDict
from django.test import override_settings
from django.urls import reverse

from borrowd_messaging.models import ChatThread, Message
from borrowd_messaging.read_state import mark_thread_read
from borrowd_messaging.services import MessagingService

from .base import MessagingTestCase


@override_settings(MESSAGING_ENABLED=True)
class SearchFilterItemNameTests(MessagingTestCase):
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
        self.assertEqual(self.thread_ids("?search=ladd"), [self.ladder.pk])

    def test_ignores_capitalisation(self) -> None:
        self.assertEqual(self.thread_ids("?search=DRILL"), [self.drill.pk])

    def test_an_empty_filter_keeps_everything(self) -> None:
        self.assertEqual(
            set(self.thread_ids("?search=")), {self.drill.pk, self.ladder.pk}
        )

    def test_a_whitespace_only_filter_keeps_everything(self) -> None:
        response = self.client.get(self.url, {"search": "   "})

        thread_ids = {card.summary.thread_id for card in response.context["cards"]}
        self.assertEqual(thread_ids, {self.drill.pk, self.ladder.pk})

    def test_a_soft_deleted_item_still_matches_by_name(self) -> None:
        self.item.soft_delete(deleted_by=self.lender)

        self.assertEqual(
            self.thread_ids("?archived=true&search=drill"), [self.drill.pk]
        )

    def test_a_hard_deleted_item_has_no_name_left_to_match(self) -> None:
        self.item.delete()

        self.assertEqual(self.thread_ids("?archived=true&search=drill"), [])
        self.assertEqual(
            ChatThread.objects.filter(pk=self.drill.pk).values_list(
                "item_id", flat=True
            )[0],
            None,
        )

    def test_filtering_never_reaches_other_peoples_conversations(self) -> None:
        stranger = self.make_user("stranger")
        self.make_thread(item=self.make_item(name="Secret Drill"), borrower=stranger)

        self.assertEqual(self.thread_ids("?search=drill"), [self.drill.pk])

    def test_scope_segments_keep_the_filter_and_return_to_the_first_page(
        self,
    ) -> None:
        response = self.client.get(self.url, {"search": "drill", "page": "2"})

        lending = next(
            segment
            for segment in response.context["scope_segments"]
            if segment["label"] == "Lending"
        )
        self.assertIn("search=drill", lending["url"])
        self.assertNotIn("page=", lending["url"])

    def test_paging_keeps_the_filter(self) -> None:
        for index in range(26):
            self.make_thread(item=self.make_item(name=f"Drill Bit {index}"))

        response = self.client.get(self.url, {"search": "drill"})

        self.assertEqual(len(response.context["cards"]), 25)
        self.assertContains(response, "search=drill")

    def test_page_links_keep_reserved_characters_in_the_filter(self) -> None:
        for index in range(26):
            self.make_thread(item=self.make_item(name=f"C++ & C# 100% {index}"))

        body = self.client.get(self.url, {"search": "C++ & C# 100%"}).content.decode()
        links = [
            QueryDict(html.unescape(href)[1:])
            for href in re.findall(r'href="(\?[^"]*)"', body)
        ]
        page_two = next(params for params in links if params.get("page") == "2")

        self.assertEqual(page_two["search"], "C++ & C# 100%")

    def test_applying_a_filter_keeps_the_open_scope(self) -> None:
        response = self.client.get(self.url, {"scope": "lending"})

        self.assertContains(response, 'name="scope" value="lending"')


@override_settings(MESSAGING_ENABLED=True)
class SearchFilterPersonNameTests(MessagingTestCase):
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
        self.assertEqual(self.thread_ids("?search=ada"), [self.with_ada.pk])

    def test_matches_a_last_name(self) -> None:
        self.assertEqual(self.thread_ids("?search=turing"), [self.with_alan.pk])

    def test_matches_a_full_name(self) -> None:
        self.assertEqual(self.thread_ids("?search=ada+lovelace"), [self.with_ada.pk])

    def test_word_order_does_not_matter(self) -> None:
        self.assertEqual(self.thread_ids("?search=lovelace+ada"), [self.with_ada.pk])

    def test_every_word_has_to_match(self) -> None:
        self.assertEqual(self.thread_ids("?search=ada+turing"), [])

    def test_only_the_first_four_distinct_words_count(self) -> None:
        self.assertEqual(
            self.thread_ids("?search=ada+lovelace+love+lace+zzz"), [self.with_ada.pk]
        )

    def test_repeated_words_do_not_use_up_the_limit(self) -> None:
        self.assertEqual(self.thread_ids("?search=ada+ADA+ada+ada+zzz"), [])

    def test_ignores_capitalisation(self) -> None:
        self.assertEqual(self.thread_ids("?search=LOVELACE"), [self.with_ada.pk])

    def test_never_matches_the_viewer_themselves(self) -> None:
        self.assertEqual(self.thread_ids("?search=grace"), [])
        self.assertEqual(self.thread_ids("?search=hopper"), [])

    def test_matches_the_borrower_when_the_viewer_is_the_lender(self) -> None:
        self.client.force_login(self.lender)

        self.assertEqual(self.thread_ids("?search=hopper"), [self.with_ada.pk])

    def test_also_matches_by_item_name(self) -> None:
        self.assertEqual(self.thread_ids("?search=ladder"), [self.with_alan.pk])


@override_settings(MESSAGING_ENABLED=True)
class LegacyItemPersonParamTests(MessagingTestCase):
    """?item=/?person= predate the combined `search` field; a bookmarked link
    using either should keep filtering rather than silently showing
    everything."""

    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("chat-thread-list")
        self.drill = self.make_thread()
        self.ladder = self.make_thread(item=self.make_item(name="Step Ladder"))
        self.client.force_login(self.borrower)

    def thread_ids(self, params: dict[str, str]) -> set[int]:
        response = self.client.get(self.url, params)
        return {card.summary.thread_id for card in response.context["cards"]}

    def test_legacy_item_param_still_filters(self) -> None:
        self.assertEqual(self.thread_ids({"item": "ladd"}), {self.ladder.pk})

    def test_legacy_person_param_still_filters(self) -> None:
        self.lender.first_name = "Ada"
        self.lender.save()

        self.assertEqual(
            self.thread_ids({"person": "ada"}), {self.drill.pk, self.ladder.pk}
        )

    def test_search_takes_precedence_over_legacy_params(self) -> None:
        self.assertEqual(
            self.thread_ids({"search": "ladd", "item": "drill"}), {self.ladder.pk}
        )

    def test_legacy_item_param_normalizes_into_search_links(self) -> None:
        response = self.client.get(self.url, {"item": "ladd"})

        lending = next(
            segment
            for segment in response.context["scope_segments"]
            if segment["label"] == "Lending"
        )
        self.assertIn("search=ladd", lending["url"])
        self.assertNotIn("item=", lending["url"])


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

        self.assertEqual(self.thread_ids("?archived=true&unread=on"), [closing.pk])

    def test_stacks_with_the_search_filter(self) -> None:
        self.assertEqual(self.thread_ids("?unread=on&search=drill"), [self.unread.pk])
        self.assertEqual(self.thread_ids("?unread=on&search=ladder"), [])

    def test_a_bookmarked_zero_turns_it_off(self) -> None:
        """A hand-edited "?unread=0" must not be read as checked."""
        self.assertEqual(
            set(self.thread_ids("?unread=0")), {self.unread.pk, self.read.pk}
        )


@override_settings(MESSAGING_ENABLED=True)
class ClearFiltersTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("chat-thread-list")
        self.make_thread()
        self.client.force_login(self.borrower)

    def test_no_clear_control_until_something_is_filtered(self) -> None:
        self.assertNotContains(self.client.get(self.url), "Clear filters")

    def test_unfiltered_text_input_starts_empty(self) -> None:
        response = self.client.get(self.url)

        self.assertContains(response, 'id="id_search"')
        self.assertNotContains(response, 'value="drill"')

    def test_an_applied_filter_offers_a_way_out(self) -> None:
        response = self.client.get(self.url, {"search": "drill"})

        self.assertContains(response, "Clear filters")
        self.assertEqual(
            response.context["clear_filters_url"], "?scope=all&archived=false"
        )

    def test_an_empty_filter_value_is_not_treated_as_filtering(self) -> None:
        response = self.client.get(self.url, {"search": ""})

        self.assertFalse(response.context["filters_applied"])
        self.assertNotContains(response, "Clear filters")

    def test_a_whitespace_only_value_is_not_treated_as_filtering(self) -> None:
        """CharField strips whitespace, so this never actually filters anything."""
        response = self.client.get(self.url, {"search": "   "})

        self.assertFalse(response.context["filters_applied"])
        self.assertNotContains(response, "Clear filters")

    def test_clearing_keeps_the_open_scope_and_archived_state(self) -> None:
        response = self.client.get(self.url, {"archived": "true", "search": "drill"})

        self.assertEqual(
            response.context["clear_filters_url"], "?scope=all&archived=true"
        )

    def test_the_unread_chip_counts_as_a_filter(self) -> None:
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

        response = self.client.get(self.url, {"search": "nothing-like-this"})

        self.assertContains(response, "No conversations match your filters.")
        self.assertNotContains(response, "No active conversations.")

    def test_an_unfiltered_empty_archived_scope_still_names_it(self) -> None:
        self.make_thread()

        response = self.client.get(self.url, {"archived": "true"})

        self.assertContains(response, "No archived conversations.")
        self.assertNotContains(response, "No conversations match your filters.")

    def test_an_empty_scope_names_itself_even_when_other_scopes_have_conversations(
        self,
    ) -> None:
        # self.borrower is the borrower on this thread, not the lender, so
        # the Lending scope is empty even though All/Borrowing are not.
        self.make_thread()

        response = self.client.get(self.url, {"scope": "lending"})

        self.assertContains(response, "No active lending conversations.")

    def test_an_empty_archived_scope_names_both_qualifiers(self) -> None:
        self.make_thread()

        response = self.client.get(self.url, {"scope": "lending", "archived": "true"})

        self.assertContains(response, "No archived lending conversations.")

    def test_someone_with_nothing_at_all_is_not_told_about_filters(self) -> None:
        response = self.client.get(self.url, {"search": "drill"})

        self.assertContains(response, "no conversations yet")
        self.assertNotContains(response, "No conversations match your filters.")

    def test_the_filters_stay_on_screen_when_nothing_matches(self) -> None:
        self.make_thread()

        response = self.client.get(self.url, {"search": "nothing-like-this"})

        self.assertContains(response, "Clear filters")
        self.assertContains(response, 'value="nothing-like-this"')
