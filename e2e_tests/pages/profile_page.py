import re

from playwright.sync_api import Page, expect


class ProfilePage:
    def __init__(self, page: Page):
        self.page = page
        self.heading = page.get_by_role("heading", name="Profile")
        self.personal_info_toggle = page.locator(
            "summary", has_text="Personal information"
        )
        self.first_name_input = page.locator("#id_first_name")
        self.last_name_input = page.locator("#id_last_name")
        self.email_input = page.locator("#id_email")
        self.bio_input = page.locator("#id_bio")
        self.update_button = page.get_by_role("button", name="Update profile")

    def expect_opened(self):
        expect(self.page).to_have_url(re.compile(r"/profile/?$"))
        expect(self.heading).to_be_visible()
        expect(self.personal_info_toggle).to_be_visible()

    def open_personal_info(self):
        """The personal info fields live in a drawer that starts collapsed.

        The drawer is Alpine-driven (CDN script, deferred). A click before
        Alpine initializes toggles the native <details> without setting
        openDrawer, leaving the two permanently out of sync until the next
        reload. Wait for Alpine to claim the drawer before clicking.
        """
        self.page.wait_for_function(
            "() => !!document.querySelector('[x-data]')?._x_dataStack"
        )
        self.personal_info_toggle.click()
        expect(self.first_name_input).to_be_visible()
        expect(self.last_name_input).to_be_visible()
        expect(self.email_input).to_be_visible()
        expect(self.bio_input).to_be_visible()
        expect(self.update_button).to_be_visible()

    def fill_bio(self, bio: str):
        self.bio_input.clear()
        self.bio_input.fill(bio)

    def click_update(self):
        expect(self.update_button).to_be_visible()
        self.update_button.click()

    def expect_bio_value(self, bio: str):
        expect(self.bio_input).to_have_value(bio)
