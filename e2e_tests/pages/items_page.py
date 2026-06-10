import re

from playwright.sync_api import Page, expect


class ItemsPage:
    def __init__(self, page: Page):
        self.page = page
        self.search_input = self.page.get_by_placeholder("Search for an item")
        self.search_button = self.page.get_by_role("button", name="Search")

    def expect_opened(self):
        expect(self.page).to_have_url(re.compile(r"/items/?$"))
        expect(self.search_input).to_be_visible()
        expect(self.search_button).to_be_visible()
