import re

from playwright.sync_api import Page, expect


class NotificationBellPage:
    """The notification bell and its click-to-open dropdown, present in the
    header on every authenticated page."""

    def __init__(self, page: Page):
        self.page = page
        self.bell_trigger = page.get_by_role("button", name="Notifications")
        self.badge = page.locator("#nav-unread-count")
        self.popup_list = page.locator("#notification-popup-list")
        self.popup_cards = page.get_by_test_id("notification-card")
        self.popup_empty_state = page.get_by_text("No notifications yet.")
        self.view_all_link = page.get_by_role("link", name="View all")
        self.inbox_heading = page.get_by_role("heading", name="Notifications")

    def open(self):
        self.bell_trigger.click()
        expect(self.popup_list).to_be_visible()

    def expect_popup_has_content_or_empty_state(self):
        expect(self.popup_cards.first.or_(self.popup_empty_state)).to_be_visible()

    def click_view_all(self):
        expect(self.view_all_link).to_be_visible()
        self.view_all_link.click()
        expect(self.page).to_have_url(re.compile(r"/notifications/?$"))
        expect(self.inbox_heading).to_be_visible()
