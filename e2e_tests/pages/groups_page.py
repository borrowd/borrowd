import re

from playwright.sync_api import Page, expect


class GroupsPage:
    def __init__(self, page: Page):
        self.page = page
        self.heading = page.get_by_role("heading", name="Groups")
        self.moderator_toggle = page.get_by_role("checkbox", name="Groups I manage")
        self.create_group_button = page.get_by_role(
            "link", name=re.compile("create group", re.I)
        )
        self.first_group_link = page.locator("#groups-card-container a").first

    def expect_opened(self):
        expect(self.page).to_have_url(re.compile(r"/groups/?$"))
        expect(self.heading).to_be_visible()
        expect(self.moderator_toggle).to_be_visible()
        expect(self.create_group_button).to_be_visible()

    def click_first_group(self):
        expect(self.first_group_link).to_be_visible()
        self.first_group_link.click()

    def click_create_group_button(self):
        expect(self.create_group_button).to_be_visible()
        self.create_group_button.click()

    def expect_group_in_list(self, name: str):
        expect(self.page.get_by_role("link", name=name, exact=True)).to_be_visible()

    def expect_group_not_in_list(self, name: str):
        expect(
            self.page.get_by_role("link", name=name, exact=True)
        ).not_to_be_attached()

    def click_group_by_name(self, name: str):
        link = self.page.get_by_role("link", name=name, exact=True)
        expect(link).to_be_visible()
        link.click()
