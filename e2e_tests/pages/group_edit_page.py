import re

from playwright.sync_api import Page, expect


class GroupEditPage:
    def __init__(self, page: Page):
        self.page = page

        self.edit_group_heading = page.get_by_role("heading", name="Edit group")
        self.group_name_input = page.get_by_role("textbox", name="Group name")
        self.group_description_input = page.get_by_role(
            "textbox", name="Group description"
        )
        self.banner_submit_input = page.locator("#banner-submit-input")
        self.approval_checkbox = page.locator("#id_membership_requires_approval")

        self.save_button = page.get_by_role("button", name="Save group")
        self.cancel_button = page.get_by_role("link", name="Cancel")

    def expect_opened(self):
        expect(self.page).to_have_url(re.compile(r"/groups/\d+/edit/?$"))
        expect(self.edit_group_heading).to_be_visible()
        expect(self.group_name_input).to_be_visible()
        expect(self.group_description_input).to_be_visible()
        expect(self.save_button).to_be_visible()

    def fill_group_name(self, name: str):
        self.group_name_input.fill(name)

    def fill_group_description(self, description: str):
        self.group_description_input.fill(description)

    def upload_banner(self, file_path: str):
        self.banner_submit_input.set_input_files(file_path)

    def click_save(self):
        expect(self.save_button).to_be_enabled()
        self.save_button.click()
