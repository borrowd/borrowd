import re

from playwright.sync_api import Page, expect


class ItemDetails:
    def __init__(self, page: Page):
        self.page = page

        self.item_details_heading = page.get_by_role("heading", name="Item details")

        self.edit_button = page.get_by_role("link", name="Edit")
        self.yours_badge = page.get_by_text("Yours", exact=True)

        # confirm request modal
        self.confirm_requst_modal = page.locator("#form-request-item-modal-search-85")
        self.confirm_requst_modal_heading = self.confirm_requst_modal.get_by_role(
            "heading", name="Confirm Request"
        )
        self.confirm_requst_modal_liability_agreement = (
            self.confirm_requst_modal.get_by_role(
                "link", name="Borrower–Lender Liability"
            )
        )
        self.confirm_requst_modal_code_of_conduct = (
            self.confirm_requst_modal.get_by_role(
                "link", name="Borrow'd Code of Conduct"
            )
        )
        self.confirm_requst_modal_agree_button = self.confirm_requst_modal.get_by_role(
            "button", name="Agree"
        )

        # accept request modal
        self.accept_request_modal = page.locator("#accept-request-modal-search-85")
        self.lend_with_care_text = self.accept_request_modal.get_by_text(
            "Let's lend with care", exact=True
        )

    def item_image(self, name: str):
        return self.page.get_by_role("img", name=re.compile(re.escape(name)))

    def item_name(self, name: str):
        return self.page.get_by_role("heading", name=name)

    def category(self, name: str):
        return self.page.get_by_text(name)

    def item_description_text(self, text: str):
        return self.page.get_by_text(text, exact=True)

    def click_edit(self):
        expect(self.edit_button).to_be_visible()
        self.edit_button.click()

    def expect_opened(self):
        expect(self.page).to_have_url(re.compile(r"/items/\d+/?(\?.*)?$"))
        expect(self.item_details_heading).to_be_visible()
        expect(self.edit_button).to_be_visible()
        expect(self.yours_badge).to_be_visible()

    def expect_photo_visible(self, name: str):
        expect(self.item_image(name)).to_be_visible()

    def expect_categories(self, categories: list[str]):
        for category in categories:
            expect(self.category(category)).to_be_visible()

    def expect_details(self, name: str, description: str):
        expect(self.item_name(name)).to_be_visible()
        expect(self.item_description_text(description)).to_be_visible()
