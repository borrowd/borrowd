"""
The menu badges (Messages, Community requests, Groups) and the navbar dot.

Messages and Community requests count only what is new since the user last
opened that section. Group actions count until each one is resolved. The
navbar dot shows while any badge is non-zero.
"""

import re

from django.http import HttpResponse
from django.http.response import HttpResponseBase
from django.test import override_settings
from django.urls import reverse

from borrowd_community_requests.models import CommunityRequest, CommunityRequestStatus
from borrowd_groups.models import Membership, MembershipStatus
from borrowd_items.models import ItemCategory
from borrowd_messaging.models import ArchiveReason, Message
from borrowd_messaging.read_state import unread_threads_for
from borrowd_messaging.services import MessagingService
from borrowd_messaging.tests.base import MessagingTestCase

MESSAGES = "nav-messages-unread-count"
COMMUNITY_REQUESTS = "nav-community-request-count-indicator"
GROUP_ACTIONS = "nav-group-action-count-indicator"
MENU_DOT = 'data-testid="nav-menu-dot"'


def badge_count(response: HttpResponseBase, testid: str) -> int:
    """The number shown in a menu badge, or 0 when the badge is not rendered."""
    assert isinstance(response, HttpResponse)
    match = re.search(
        rf'data-testid="{testid}">\s*(\d+)\s*<', response.content.decode()
    )
    return int(match.group(1)) if match else 0


@override_settings(MESSAGING_ENABLED=True)
class MenuBadgeTestCase(MessagingTestCase):
    """
    The viewer is `self.borrower`, sharing a group with `self.lender`, who
    moderates it. Each test adds only what it is checking.
    """

    def setUp(self) -> None:
        super().setUp()
        self.group = self.make_group()
        self.group.add_user(self.borrower)
        self.category = ItemCategory.objects.create(name="Tools")
        self.client.force_login(self.borrower)

    def menu(self) -> HttpResponseBase:
        """Any page other than the sections themselves, to read the menu."""
        response = self.client.get(reverse("item-list"))
        self.assertEqual(response.status_code, 200)
        return response

    def receive_message(self, body: str = "Is it free?") -> Message:
        """An incoming message in a new conversation about a new item."""
        return Message.objects.create(
            thread=self.make_thread(item=self.make_item()),
            sender=self.lender,
            body=body,
        )

    def receive_community_request(self, item_name: str = "Ladder") -> CommunityRequest:
        return CommunityRequest.objects.create(
            requester=self.lender, category=self.category, item_name=item_name
        )

    def open_messages(self) -> None:
        self.assertEqual(self.client.get(reverse("chat-thread-list")).status_code, 200)

    def open_community_requests(self) -> None:
        response = self.client.get(reverse("community-request-list"))
        self.assertEqual(response.status_code, 200)

    def make_pending_request_to_join(self, username: str = "applicant") -> Membership:
        """A join request awaiting the viewer, who moderates the group."""
        group = self.make_group(
            f"Approval {username}",
            created_by=self.borrower,
            updated_by=self.borrower,
            membership_requires_approval=True,
        )
        membership = group.add_user(self.make_user(username))
        self.assertEqual(membership.status, MembershipStatus.PENDING)
        return membership


class NewItemsClearOnViewTests(MenuBadgeTestCase):
    """1. Messages and Community requests count only new items."""

    def test_messages_badge_clears_when_messages_is_opened(self) -> None:
        self.receive_message()
        self.assertEqual(badge_count(self.menu(), MESSAGES), 1)

        self.open_messages()

        self.assertEqual(badge_count(self.menu(), MESSAGES), 0)
        # The conversation itself stays unread until it is opened.
        self.assertTrue(unread_threads_for(self.borrower).exists())

    def test_messages_page_itself_renders_the_cleared_badge(self) -> None:
        self.receive_message()
        response = self.client.get(reverse("chat-thread-list"))
        self.assertEqual(badge_count(response, MESSAGES), 0)

    def test_message_sent_after_opening_messages_counts(self) -> None:
        self.receive_message()
        self.open_messages()

        self.receive_message("Still around?")

        self.assertEqual(badge_count(self.menu(), MESSAGES), 1)

    def test_own_message_after_opening_messages_does_not_count(self) -> None:
        self.open_messages()
        Message.objects.create(
            thread=self.make_thread(), sender=self.borrower, body="Hello."
        )
        self.assertEqual(badge_count(self.menu(), MESSAGES), 0)

    def test_community_requests_badge_clears_when_page_is_opened(self) -> None:
        self.receive_community_request()
        self.assertEqual(badge_count(self.menu(), COMMUNITY_REQUESTS), 1)

        self.open_community_requests()

        self.assertEqual(badge_count(self.menu(), COMMUNITY_REQUESTS), 0)

    def test_community_request_created_after_opening_counts(self) -> None:
        self.receive_community_request()
        self.open_community_requests()

        self.receive_community_request("Wheelbarrow")

        self.assertEqual(badge_count(self.menu(), COMMUNITY_REQUESTS), 1)

    def test_opening_one_section_leaves_the_other_badge(self) -> None:
        self.receive_message()
        self.receive_community_request()

        self.open_messages()

        menu = self.menu()
        self.assertEqual(badge_count(menu, MESSAGES), 0)
        self.assertEqual(badge_count(menu, COMMUNITY_REQUESTS), 1)

    def test_opening_a_section_clears_only_the_viewers_badge(self) -> None:
        neighbour = self.make_user("neighbour")
        self.group.add_user(neighbour)
        self.receive_community_request()

        self.open_community_requests()
        self.client.force_login(neighbour)

        self.assertEqual(badge_count(self.menu(), COMMUNITY_REQUESTS), 1)


class SeenOpenRequestTests(MenuBadgeTestCase):
    """2. A seen community request no longer counts, even while still open."""

    def test_seen_request_that_is_still_open_does_not_count(self) -> None:
        community_request = self.receive_community_request()
        self.open_community_requests()

        community_request.refresh_from_db()
        self.assertEqual(community_request.status, CommunityRequestStatus.OPEN)
        self.assertEqual(badge_count(self.menu(), COMMUNITY_REQUESTS), 0)


class ArchivedMessagesTests(MenuBadgeTestCase):
    """3. Archived conversations never count toward the Messages badge."""

    def test_archiving_notice_does_not_count(self) -> None:
        MessagingService.archive_thread(self.make_thread(), ArchiveReason.CLOSED)
        self.assertEqual(badge_count(self.menu(), MESSAGES), 0)

    def test_unread_messages_stop_counting_once_the_thread_is_archived(self) -> None:
        message = self.receive_message()
        self.assertEqual(badge_count(self.menu(), MESSAGES), 1)

        MessagingService.archive_thread(message.thread, ArchiveReason.RETURNED)

        self.assertEqual(badge_count(self.menu(), MESSAGES), 0)

    def test_archived_thread_does_not_mask_an_active_one(self) -> None:
        MessagingService.archive_thread(self.make_thread(), ArchiveReason.CLOSED)
        Message.objects.create(
            thread=self.make_thread(item=self.make_item(name="Saw")),
            sender=self.lender,
            body="Is it free?",
        )
        self.assertEqual(badge_count(self.menu(), MESSAGES), 1)


class GroupActionBadgeTests(MenuBadgeTestCase):
    """4. Moderators see a badge for pending requests to join their groups."""

    def test_moderator_sees_count_of_pending_requests(self) -> None:
        self.make_pending_request_to_join("first")
        self.make_pending_request_to_join("second")
        self.assertEqual(badge_count(self.menu(), GROUP_ACTIONS), 2)

    def test_non_moderator_member_sees_no_badge(self) -> None:
        membership = self.make_pending_request_to_join()
        member = self.make_user("member")
        Membership.objects.create(
            user=member, group=membership.group, status=MembershipStatus.ACTIVE
        )

        self.client.force_login(member)

        self.assertEqual(badge_count(self.menu(), GROUP_ACTIONS), 0)

    def test_applicant_sees_no_badge_for_their_own_request(self) -> None:
        membership = self.make_pending_request_to_join()
        self.client.force_login(membership.user)
        self.assertEqual(badge_count(self.menu(), GROUP_ACTIONS), 0)

    def test_moderator_whose_membership_ended_sees_no_badge(self) -> None:
        membership = self.make_pending_request_to_join()
        Membership.objects.filter(user=self.borrower, group=membership.group).update(
            status=MembershipStatus.ENDED
        )
        self.assertEqual(badge_count(self.menu(), GROUP_ACTIONS), 0)

    def test_group_needing_a_moderator_counts_as_an_action(self) -> None:
        Membership.objects.filter(user=self.lender, group=self.group).update(
            is_moderator=False
        )
        menu = self.menu()
        self.assertEqual(badge_count(menu, GROUP_ACTIONS), 1)
        self.assertContains(
            menu, 'data-testid="nav-groups-needing-moderator-indicator"'
        )


class GroupActionPersistenceTests(MenuBadgeTestCase):
    """5. Group action badges persist until each request is resolved."""

    def test_opening_groups_does_not_clear_the_badge(self) -> None:
        membership = self.make_pending_request_to_join()

        self.client.get(reverse("borrowd_groups:group-list"))
        self.client.get(
            reverse("borrowd_groups:group-detail", args=[membership.group_id])
        )

        self.assertEqual(badge_count(self.menu(), GROUP_ACTIONS), 1)

    def test_approving_and_denying_each_clear_one_request(self) -> None:
        to_approve = self.make_pending_request_to_join("approve")
        to_deny = self.make_pending_request_to_join("deny")
        self.assertEqual(badge_count(self.menu(), GROUP_ACTIONS), 2)

        self.client.post(reverse("borrowd_groups:approve-member", args=[to_approve.pk]))
        self.assertEqual(badge_count(self.menu(), GROUP_ACTIONS), 1)

        self.client.post(reverse("borrowd_groups:deny-member", args=[to_deny.pk]))
        self.assertEqual(badge_count(self.menu(), GROUP_ACTIONS), 0)


class NavbarDotTests(MenuBadgeTestCase):
    """6. The navbar dot shows if and only if some menu badge is non-zero."""

    def test_no_dot_when_every_badge_is_zero(self) -> None:
        menu = self.menu()
        self.assertNotContains(menu, MENU_DOT)
        self.assertContains(menu, 'aria-label="Menu"')

    def test_each_badge_alone_shows_the_dot(self) -> None:
        sources = {
            "messages": self.receive_message,
            "community requests": self.receive_community_request,
            "group actions": self.make_pending_request_to_join,
        }
        for name, create in sources.items():
            with self.subTest(name):
                create()
                menu = self.menu()
                self.assertContains(menu, MENU_DOT, count=1)
                self.assertContains(menu, 'aria-label="Menu, unread items"')
                # Reset for the next source.
                CommunityRequest.objects.all().delete()
                Message.objects.all().delete()
                Membership.objects.filter(status=MembershipStatus.PENDING).delete()

    def test_dot_clears_once_everything_is_seen(self) -> None:
        self.receive_message()
        self.receive_community_request()
        self.assertContains(self.menu(), MENU_DOT)

        self.open_messages()
        self.open_community_requests()

        self.assertNotContains(self.menu(), MENU_DOT)

    def test_dot_stays_while_group_actions_are_pending(self) -> None:
        self.receive_message()
        self.receive_community_request()
        self.make_pending_request_to_join()

        self.open_messages()
        self.open_community_requests()

        self.assertContains(self.menu(), MENU_DOT)

    def test_badge_refresh_updates_the_dot_out_of_band(self) -> None:
        url = reverse("chat-thread-unread-badge")
        message = self.receive_message()

        with_unread = self.client.get(url)
        self.assertContains(with_unread, 'id="nav-menu-toggle"')
        self.assertContains(with_unread, 'hx-swap-oob="true"')
        self.assertContains(with_unread, MENU_DOT)

        self.client.post(
            reverse("chat-thread-read", args=[message.thread_id]),
            {"through": message.pk},
        )

        self.assertNotContains(self.client.get(url), MENU_DOT)

    def test_badge_refresh_keeps_the_dot_for_other_badges(self) -> None:
        self.make_pending_request_to_join()
        response = self.client.get(reverse("chat-thread-unread-badge"))
        self.assertEqual(badge_count(response, MESSAGES), 0)
        self.assertContains(response, MENU_DOT)
