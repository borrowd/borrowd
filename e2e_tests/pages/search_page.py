import re

from playwright.sync_api import Page, expect


class SearchPage:
    def __init__(self, page: Page):
        self.page = page

        self.search_input = page.get_by_placeholder("Search for an item")
        self.search_button = page.get_by_role("button", name="Search")
        self.filter_button = page.get_by_role("button", name="Filter by category")

        # borrowing
        self.request_item_button = page.get_by_role("button", name="Request item")
        self.cancel_request_button = page.get_by_role("button", name="Cancel request")
        self.accept_request_button = page.get_by_role("button", name="Accept")
        self.decline_request_button = page.get_by_role("button", name="Decline")
        self.confirm_picked_up_button = page.get_by_role(
            "button", name="Confirm picked up"
        )
        self.confirm_returned_button = page.get_by_role(
            "button", name="Confirm returned"
        )

        # confirm request modal
        self.confirm_requst_modal = page.locator("#request-item-modal-search-85")
        self.confirm_requst_modal_heading = self.confirm_requst_modal.get_by_role(
            "heading", name="Confirm Request"
        )
        self.confirm_requst_modal_text = self.confirm_requst_modal.get_by_text(
            "Let's share with care", exact=False
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
        self.confirm_requst_modal_decline_button = (
            self.confirm_requst_modal.get_by_role("button", name="Decline")
        )

        # accept request modal
        self.accept_request_modal = page.locator("#accept-request-modal-search-85")
        self.accept_request_modal_heading = self.accept_request_modal.get_by_role(
            "heading", name="Accept Request"
        )
        self.accept_request_modal_lend_with_care_text = (
            self.accept_request_modal.get_by_text("Let's lend with care", exact=False)
        )
        self.accept_request_modal_liability_agreement = (
            self.accept_request_modal.get_by_role(
                "link", name="Borrower–Lender Liability"
            )
        )
        self.accept_request_modal_code_of_conduct = (
            self.accept_request_modal.get_by_role(
                "link", name="Borrow'd Code of Conduct"
            )
        )
        self.accept_request_modal_decline_button = (
            self.accept_request_modal.get_by_role("button", name="Decline")
        )
        self.accept_request_modal_agree_button = self.accept_request_modal.get_by_role(
            "button", name="Agree"
        )

        # confirm collection modal borrower
        self.confirm_collection_modal = page.locator("#mark-collected-modal-search-85")
        self.confirm_collection_modal_heading = (
            self.confirm_collection_modal.get_by_role(
                "heading", name="Confirm Collection"
            )
        )
        self.confirm_collection_modal_text = self.confirm_collection_modal.get_by_text(
            "Please confirm that this item", exact=False
        )
        self.confirm_collection_modal_cancel_button = (
            self.confirm_collection_modal.get_by_role("button", name="Cancel")
        )
        self.confirm_collection_modal_confirm_button = (
            self.confirm_collection_modal.get_by_role("button", name="Confirm")
        )

        # cofirm collection modal lender
        self.confirm_collection_modal_lender = page.locator(
            "#confirm-collected-modal-search-85"
        )
        self.confirm_collection_modal_lender_heading = (
            self.confirm_collection_modal_lender.get_by_role(
                "heading", name="Confirm Collection"
            )
        )
        self.confirm_collection_modal_lender_text = (
            self.confirm_collection_modal_lender.get_by_text(
                "Please confirm that this item", exact=False
            )
        )
        self.confirm_collection_modal_lender_cancel_button = (
            self.confirm_collection_modal_lender.get_by_role("button", name="Cancel")
        )
        self.confirm_collection_modal_lender_confirm_button = (
            self.confirm_collection_modal_lender.get_by_role("button", name="Confirm")
        )

        # confirm return modal
        self.confirm_returned_modal = page.locator("#mark-returned-modal-search-85")
        self.confirm_returned_modal_heading = self.confirm_returned_modal.get_by_role(
            "heading", name="Confirm Return"
        )
        self.confirm_returned_modal_text = self.confirm_returned_modal.get_by_text(
            "Please confirm that this item", exact=False
        )
        self.confirm_returned_modal_cancel_button = (
            self.confirm_returned_modal.get_by_role("button", name="Cancel")
        )
        self.confirm_returned_modal_confirm_button = (
            self.confirm_returned_modal.get_by_role("button", name="Confirm")
        )

        # confirm return modal_borrower
        self.confirm_returned_modal_borrower = page.locator(
            "#confirm-returned-modal-search-85"
        )
        self.confirm_returned_modal_borrower_heading = (
            self.confirm_returned_modal_borrower.get_by_role(
                "heading", name="Confirm Return"
            )
        )
        self.confirm_returned_modal_borrower_text = (
            self.confirm_returned_modal_borrower.get_by_text(
                "Please confirm that this item", exact=False
            )
        )
        self.confirm_returned_modal_borrower_cancel_button = (
            self.confirm_returned_modal_borrower.get_by_role("button", name="Cancel")
        )
        self.confirm_returned_modal_borrower_confirm_button = (
            self.confirm_returned_modal_borrower.get_by_role("button", name="Confirm")
        )

    def expect_opened(self):
        expect(self.search_input).to_be_visible()
        expect(self.search_button).to_be_visible()
        expect(self.filter_button).to_be_visible()

    def click_request_item(self):
        expect(self.request_item_button).to_be_visible()
        expect(self.request_item_button).to_be_enabled()
        self.request_item_button.click()

    def confirm_request_modal_opens(self):
        expect(self.confirm_requst_modal_heading).to_be_visible()
        expect(self.confirm_requst_modal_text).to_be_visible()
        expect(self.confirm_requst_modal_liability_agreement).to_be_visible()
        expect(self.confirm_requst_modal_code_of_conduct).to_be_visible()
        expect(self.confirm_requst_modal_agree_button).to_be_visible()
        expect(self.confirm_requst_modal_decline_button).to_be_visible()

    def confirm_request_modal_click_agree(self):
        expect(self.confirm_requst_modal_agree_button).to_be_enabled()
        self.confirm_requst_modal_agree_button.click()

    def expect_item_is_reqested_by_borrower(self):
        expect(self.cancel_request_button).to_be_visible()

    def expect_item_is_reqested_by_lender(self):
        expect(self.accept_request_button).to_be_visible()
        expect(self.decline_request_button).to_be_visible()

    def click_accept_borrowing_request(self):
        expect(self.accept_request_button).to_be_enabled()
        self.accept_request_button.click()

    def accept_request_modal_opens(self):
        expect(self.accept_request_modal_heading).to_be_visible()
        expect(self.accept_request_modal_lend_with_care_text).to_be_visible()
        expect(self.accept_request_modal_liability_agreement).to_be_visible()
        expect(self.accept_request_modal_code_of_conduct).to_be_visible()
        expect(self.accept_request_modal_decline_button).to_be_visible()
        expect(self.accept_request_modal_agree_button).to_be_visible()

    def accept_request_modal_click_agree(self):
        expect(self.accept_request_modal_agree_button).to_be_enabled()
        self.accept_request_modal_agree_button.click()

    def expect_request_is_accepted(self):
        expect(self.confirm_picked_up_button).to_be_visible()

    def click_confirm_pick_up(self):
        expect(self.confirm_picked_up_button).to_be_enabled()
        self.confirm_picked_up_button.click()

    def confirm_collection_modal_opens(self):
        expect(self.confirm_collection_modal_heading).to_be_visible()
        expect(self.confirm_collection_modal_text).to_be_visible()
        expect(self.confirm_collection_modal_cancel_button).to_be_visible()
        expect(self.confirm_collection_modal_confirm_button).to_be_visible()

    def confirm_collection_modal_lender_opens(self):
        expect(self.confirm_collection_modal_lender_heading).to_be_visible()
        expect(self.confirm_collection_modal_lender_text).to_be_visible()
        expect(self.confirm_collection_modal_lender_cancel_button).to_be_visible()
        expect(self.confirm_collection_modal_lender_confirm_button).to_be_visible()

    def confirm_collection_modal_click_confirm(self):
        expect(self.confirm_collection_modal_confirm_button).to_be_enabled()
        self.confirm_collection_modal_confirm_button.click()

    def confirm_collection_modal_lender_click_confirm(self):
        expect(self.confirm_collection_modal_lender_confirm_button).to_be_enabled()
        self.confirm_collection_modal_lender_confirm_button.click()

    def expect_item_is_collected(self):
        expect(self.confirm_returned_button).to_be_visible()

    def click_confirm_returned_button(self):
        expect(self.confirm_returned_button).to_be_enabled()
        self.confirm_returned_button.click()

    def confirm_returned_modal_opens(self):
        expect(self.confirm_returned_modal_heading).to_be_visible()
        expect(self.confirm_returned_modal_text).to_be_visible()
        expect(self.confirm_returned_modal_cancel_button).to_be_visible()
        expect(self.confirm_returned_modal_confirm_button).to_be_visible()

    def confirm_returned_modal_click_confirm_returned(self):
        expect(self.confirm_returned_modal_confirm_button).to_be_enabled()
        self.confirm_returned_modal_confirm_button.click()

    def confirm_returned_modal_borrower_opens(self):
        expect(self.confirm_returned_modal_borrower_heading).to_be_visible()
        expect(self.confirm_returned_modal_borrower_text).to_be_visible()
        expect(self.confirm_returned_modal_borrower_cancel_button).to_be_visible()
        expect(self.confirm_returned_modal_borrower_confirm_button).to_be_visible()

    def confirm_returned_modal_borrower_click_confirm_returned(self):
        expect(self.confirm_returned_modal_borrower_confirm_button).to_be_enabled()
        self.confirm_returned_modal_borrower_confirm_button.click()

    def expect_item_is_available(self):
        expect(self.request_item_button).to_be_visible()
        expect(self.request_item_button).to_be_enabled()
