import random
import re

from faker import Faker
from playwright.sync_api import Page, expect

fake = Faker()


class AddNewItem:
    CATEGORY_OPTIONS = [
        "Tools & Hardware",
        "Sports & Adventure",
        "Home & Kitchen Appliances",
        "Event & Party Supplies",
        "Hobbies & Crafts",
        "Electronics & Tech",
        "Kid & Baby",
        "Gardening & Yard",
        "Seasonal & Holidays",
        "Pet Supplies",
        "Office & Work",
        "Books, Games, & Media",
        "Other",
    ]

    def __init__(self, page: Page):
        self.page = page

        self.add_item_heading = page.get_by_role("heading", name="Add item")

        self.item_name_input = page.locator("#id_name")
        self.item_description_input = page.locator("#id_description")

        self.categories_button = page.get_by_role(
            "button", name="Select an item category"
        )

        # modal
        self.categories_modal = page.locator("#item-category-modal")
        self.select_categories_modal_heading = self.categories_modal.get_by_role(
            "heading", name="Select categories"
        )
        self.clear_categories_modal_button = self.categories_modal.get_by_role(
            "button", name="Clear"
        )
        self.select_categories_modal_button = self.categories_modal.get_by_role(
            "button", name="Select categories"
        )

        self.trust_select = page.locator("#id_trust_level_required")

        self.upload_photo_button = page.get_by_role("button", name="Choose File")

        self.trust_level_required_text = page.get_by_text(
            "Trust level required", exact=False
        )
        self.trust_level_description_button = page.get_by_role(
            "link", name="What is this?"
        )

        self.add_item_button = page.get_by_role(
            "button", name=re.compile(r"Add an item|Create New Item|Add item", re.I)
        )

    def expect_opened(self):
        expect(self.add_item_heading).to_be_visible()
        expect(self.item_name_input).to_be_visible()
        expect(self.item_description_input).to_be_visible()
        expect(self.categories_button).to_be_visible()
        expect(self.trust_level_required_text).to_be_visible()
        expect(self.trust_select).to_be_visible()

    def fill_item_name(self, item_name: str):
        self.item_name_input.fill(item_name)

    def fill_item_description(self, item_description: str):
        self.item_description_input.fill(item_description)

    def click_categories_button(self):
        expect(self.categories_button).to_be_visible()
        self.categories_button.click()

    def expect_modal_with_categories_opened(self):
        expect(self.categories_modal).to_be_visible()
        expect(self.select_categories_modal_heading).to_be_visible()
        expect(self.clear_categories_modal_button).to_be_visible()
        expect(self.select_categories_modal_button).to_be_disabled()

    def select_random_categories(
        self, available: list[str], min_count=1, max_count=3
    ) -> list[str]:
        count = random.randint(min_count, min(max_count, len(available)))
        chosen = random.sample(available, count)

        for category in chosen:
            option = self.categories_modal.get_by_role("button", name=category)
            expect(option).to_be_visible()
            option.click()

        expect(self.select_categories_modal_button).to_be_enabled()
        self.select_categories_modal_button.click()

        return chosen

    def choose_random_trust_level(self) -> str:
        levels = ["Standard", "High"]
        chosen = random.choice(levels)

        self.trust_select.select_option(label=chosen)

        option_value = self.trust_select.locator(
            "option", has_text=chosen
        ).get_attribute("value")
        expect(self.trust_select).to_have_value(option_value or "")

        return chosen

    def click_upload_photo_button(self):
        expect(self.upload_photo_button).to_be_visible()
        self.upload_photo_button.click()

    def upload_photo(self, file_path: str):
        self.page.locator('input[type="file"]').set_input_files(file_path)

    def click_add_item_button(self):
        expect(self.add_item_button).to_be_visible()
        self.add_item_button.click()
