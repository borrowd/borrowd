import re

from playwright.sync_api import Page, expect


class ItemEditPage:
    def __init__(self, page: Page):
        self.page = page
        self.heading = page.get_by_role("heading", name="Edit item")
        self.name_input = page.locator("#id_name")
        self.description_input = page.locator("#id_description")
        self.save_button = page.get_by_role("button", name="Save changes")
        self.cancel_button = page.get_by_role("link", name="Cancel")
        self.delete_button = page.get_by_role("button", name="Delete item")
        self.delete_modal = page.locator("#item-delete-modal")
        self.delete_modal_confirm_button = self.delete_modal.get_by_role(
            "button", name="Yes, delete item"
        )

    def expect_opened(self):
        expect(self.page).to_have_url(re.compile(r"/items/\d+/edit/?$"))
        expect(self.heading).to_be_visible()
        expect(self.save_button).to_be_visible()
        expect(self.delete_button).to_be_visible()

    def fill_name(self, name: str):
        self.name_input.clear()
        self.name_input.fill(name)

    def fill_description(self, description: str):
        self.description_input.clear()
        self.description_input.fill(description)

    def click_save(self):
        expect(self.save_button).to_be_visible()
        self.save_button.click()

    def click_cancel(self):
        expect(self.cancel_button).to_be_visible()
        self.cancel_button.click()

    def click_delete_item(self):
        expect(self.delete_button).to_be_visible()
        self.delete_button.click()

    def expect_delete_modal_opened(self):
        expect(self.delete_modal).to_be_visible()

    def confirm_delete(self):
        expect(self.delete_modal_confirm_button).to_be_visible()
        self.delete_modal_confirm_button.click()
