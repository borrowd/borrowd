import re

from playwright.sync_api import Page, expect


class InventoryPage:
    def __init__(self, page: Page):
        self.page = page

        self.heading = page.get_by_role("heading", name="Inventory")

        self.your_items_toggle = page.get_by_role("switch", name="Your items")
        self.add_item_button = page.get_by_role(
            "link", name=re.compile(r"Add an item|Create New Item|Add item", re.I)
        )

    def expect_opened(self):
        expect(self.heading).to_be_visible()
        expect(self.your_items_toggle).to_be_visible()

    def click_add_item_button(self):
        expect(self.add_item_button).to_be_visible()
        self.add_item_button.click()

    def click_item_by_name(self, name: str):
        item_link = self.page.get_by_role("heading", name=name)
        expect(item_link).to_be_visible()
        item_link.click()

    def expect_item_not_in_inventory(self, name: str):
        expect(self.page.get_by_role("heading", name=name)).not_to_be_attached()
