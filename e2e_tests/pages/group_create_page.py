import random
import re

from faker import Faker
from playwright.sync_api import Page, expect

fake = Faker()


class GroupCreatePage:
    def __init__(self, page: Page):
        self.page = page

        self.create_group_heading = page.get_by_role("heading", name="Create a group")
        self.group_name_input = page.get_by_role("textbox", name="Group name")
        self.group_description_input = page.get_by_role(
            "textbox", name="Group description"
        )

        self.trust_select = page.get_by_label(
            re.compile("what do you want your trust", re.I)
        )

        self.upload_banner_button = page.get_by_role(
            "button", name="Picture (optional)"
        )
        self.banner_submit_input = page.locator("#banner-submit-input")

        self.approval_checkbox = page.locator("#id_membership_requires_approval")
        self.approval_checkbox_description = page.get_by_text(
            "New members require Moderator", exact=False
        )

        self.create_group_button = page.get_by_role(
            "button", name=re.compile("create group", re.I)
        )

    def expect_opened(self):
        expect(self.create_group_heading).to_be_visible()
        expect(self.group_name_input).to_be_visible()
        expect(self.group_description_input).to_be_visible()
        expect(self.trust_select).to_be_visible()
        expect(self.approval_checkbox_description).to_be_visible()

    def fill_group_name(self, group_name: str):
        self.group_name_input.fill(group_name)

    def fill_group_description(self, description: str):
        self.group_description_input.fill(description)

    def set_approval_checkbox(self, value: bool):
        if value:
            self.approval_checkbox.check()
            expect(self.approval_checkbox).to_be_checked()
        else:
            self.approval_checkbox.uncheck()
            expect(self.approval_checkbox).not_to_be_checked()

    def set_random_trust_level(self) -> str:
        options = [
            ("1", "Standard"),
            ("2", "High"),
        ]
        value, label = random.choice(options)
        self.trust_select.select_option(value)
        return value

    def open_upload_banner(self):
        self.upload_banner_button.click()

    def upload_banner(self, file_path: str):
        self.banner_submit_input.set_input_files(file_path)

    def click_create_group_button(self):
        expect(self.create_group_button).to_be_visible()
        self.create_group_button.click()
