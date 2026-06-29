import re

from playwright.sync_api import Page, expect


class GroupInvitePage:
    def __init__(self, page: Page):
        self.page = page
        self.invite_link_heading = page.get_by_role("heading", name="Invite link")
        self.qr_canvas = page.locator("canvas[data-qr-value]")
        self.join_link = page.locator("#join-link")
        self.copy_button = page.get_by_role("button", name="Copy link")

    def expect_opened(self):
        expect(self.page).to_have_url(re.compile(r"/groups/\d+/invite/?$"))
        expect(self.invite_link_heading).to_be_visible()
        expect(self.qr_canvas).to_be_visible()
        expect(self.join_link).to_be_visible()
        expect(self.copy_button).to_be_visible()

    def expect_group_name(self, name: str):
        expect(self.page.get_by_role("heading", name=name)).to_be_visible()

    def expect_join_link_not_empty(self):
        expect(self.join_link).not_to_be_empty()
