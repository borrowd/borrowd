import allure
import pytest
from pages.search_page import SearchPage
from playwright.sync_api._generated import Page


@pytest.mark.skip(reason="WIP: hardcoded item ID, needs rework")
@pytest.mark.smoke
@pytest.mark.regression
@allure.feature("Borrowing")
@allure.title("Full borrow and return flow — from request to confirmed return")
@allure.severity(allure.severity_level.BLOCKER)
def test_borrow_and_return_item(borrower_page: Page, lender_page: Page):
    borrower_search_page = SearchPage(borrower_page)
    lender_search_page = SearchPage(lender_page)

    with allure.step("Borrower requests the item"):
        borrower_search_page.expect_opened()
        borrower_search_page.click_request_item()
        borrower_search_page.confirm_request_modal_opens()
        borrower_search_page.confirm_request_modal_click_agree()
        borrower_search_page.expect_item_is_reqested_by_borrower()

    with allure.step("Lender accepts the request"):
        lender_search_page.page.reload()
        lender_search_page.expect_opened()
        lender_search_page.expect_item_is_reqested_by_lender()
        lender_search_page.click_accept_borrowing_request()
        lender_search_page.accept_request_modal_opens()
        lender_search_page.accept_request_modal_click_agree()
        lender_search_page.expect_request_is_accepted()

    with allure.step("Borrower confirms pickup"):
        borrower_search_page.page.reload()
        borrower_search_page.expect_request_is_accepted()
        borrower_search_page.click_confirm_pick_up()
        borrower_search_page.confirm_collection_modal_opens()
        borrower_search_page.confirm_collection_modal_click_confirm()

    with allure.step("Lender confirms pickup"):
        lender_search_page.page.reload()
        lender_search_page.click_confirm_pick_up()
        lender_search_page.confirm_collection_modal_lender_opens()
        lender_search_page.confirm_collection_modal_lender_click_confirm()
        lender_search_page.expect_item_is_collected()

    with allure.step("Lender marks item as returned"):
        lender_search_page.page.reload()
        lender_search_page.click_confirm_returned_button()
        lender_search_page.confirm_returned_modal_opens()
        lender_search_page.confirm_returned_modal_click_confirm_returned()

    with allure.step("Borrower confirms return"):
        borrower_search_page.page.reload()
        borrower_search_page.click_confirm_returned_button()
        borrower_search_page.confirm_returned_modal_borrower_opens()
        borrower_search_page.confirm_returned_modal_borrower_click_confirm_returned()

    with allure.step("Item is available again"):
        borrower_search_page.page.reload()
        borrower_search_page.expect_opened()
        borrower_search_page.expect_item_is_available()
