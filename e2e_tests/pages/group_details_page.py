import re

from playwright.sync_api import Page, expect


class GroupDetails:
    def __init__(self, page: Page):
        self.page = page

        self.group_details_heading = page.get_by_role("heading", name="Group details")
        self.banner_image = page.get_by_role("img", name="Group Banner Image")

        self.get_invite_link_button = page.get_by_role("link", name="Get invite link")

        self.members_heading = page.get_by_role(
            "heading", name=re.compile("members", re.I)
        )
        self.user_role = page.get_by_text("Moderator", exact=True)

        self.edit_group_button = page.get_by_role("link", name="Edit group")

        # "Leave group" appears twice in the DOM once the confirm modal is
        # open (the page trigger button + the modal's own submit button, both
        # with the same accessible name) — scope the confirm button to its
        # dialog so locating either one stays unambiguous.
        self.leave_group_button = page.get_by_role("button", name="Leave group")
        self.leave_group_moderator_confirm_button = page.locator(
            "#leave-group-moderator-confirm-modal"
        ).get_by_role("button", name="Leave group")

    def group_name(self, name: str):
        return self.page.get_by_role("heading", name=name)

    def description_text(self, text: str):
        return self.page.get_by_text(text, exact=True)

    def expect_opened(self):
        expect(self.page).to_have_url(re.compile(r"/groups/\d+/?$"), timeout=5_000)
        expect(self.group_details_heading).to_be_visible()
        expect(self.get_invite_link_button).to_be_visible()
        expect(self.edit_group_button).to_be_visible()

    def expect_banner_visible(self):
        expect(self.banner_image).to_be_visible()

    def expect_details(self, name: str, description: str):
        expect(self.group_name(name)).to_be_visible()
        expect(self.description_text(description)).to_be_visible()

    def expect_members_count(self, count: int):
        expect(
            self.page.get_by_role("heading", name=f"Members ({count})")
        ).to_be_visible()

    def expect_you_are_moderator(self):
        expect(self.user_role).to_be_visible()

    def click_get_invite_link(self):
        expect(self.get_invite_link_button).to_be_visible()
        self.get_invite_link_button.click()

    def click_edit_group(self):
        expect(self.edit_group_button).to_be_visible()
        self.edit_group_button.click()

    def leave_group_as_sole_moderator(self):
        """Leaving as the group's only active member deletes the group
        server-side (LeaveGroupView.post), so this doubles as the only
        available cleanup path for e2e-created groups."""
        expect(self.leave_group_button).to_be_visible()
        self.leave_group_button.click()
        expect(self.leave_group_moderator_confirm_button).to_be_visible()
        self.leave_group_moderator_confirm_button.click()
