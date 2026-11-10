import re
from datetime import datetime

import allure
import pytest
from faker import Faker
from pages.inventory_page import InventoryPage
from pages.item_add_new_page import AddNewItem
from pages.search_page import SearchPage
from playwright.sync_api import Page, expect

fake = Faker()


def _create_item_as_lender(lender_page: Page, base_url: str, item_name: str) -> str:
    """Create an item shared with all of the lender's groups; return its id."""
    lender_page.goto(f"{base_url}/profile/inventory/", wait_until="domcontentloaded")
    inventory = InventoryPage(lender_page)
    inventory.expect_opened()
    inventory.click_add_item_button()

    add = AddNewItem(lender_page)
    add.expect_opened()
    add.fill_item_name(item_name)
    add.fill_item_description(fake.text(max_nb_chars=100))
    add.click_categories_button()
    add.select_random_categories(available=["Other"], min_count=1, max_count=1)
    add.click_add_item_button()

    inventory.expect_opened()
    inventory.click_item_by_name(item_name)
    expect(lender_page).to_have_url(re.compile(r"/items/\d+/?(\?.*)?$"))
    match = re.search(r"/items/(\d+)", lender_page.url)
    assert match is not None
    return match.group(1)


@pytest.mark.regression
@allure.feature("Borrowing")
@allure.title("Full borrow and return flow — from request to confirmed return")
@allure.severity(allure.severity_level.BLOCKER)
def test_borrow_and_return_item(borrower_page: Page, lender_page: Page, base_url):
    item_name = f"E2E borrow {datetime.now().strftime('%H%M%S')}"

    with allure.step("Lender creates an item shared with the group"):
        item_id = _create_item_as_lender(lender_page, base_url, item_name)

    borrower_search_page = SearchPage(borrower_page, item_id)
    # The lender acts on their own item from the inventory, where each card
    # sits in a section named for the item's current state.
    lender_incoming_request = SearchPage(
        lender_page, item_id, "incoming-borrow-requests"
    )
    lender_lent_item = SearchPage(lender_page, item_id, "owned-items-lent")

    with allure.step("Borrower requests the item"):
        borrower_search_page.open_and_search(base_url, item_name)
        borrower_search_page.click_request_item()
        borrower_search_page.confirm_request_modal_opens()
        borrower_search_page.confirm_request_modal_click_agree()
        borrower_search_page.expect_item_is_reqested_by_borrower()

    with allure.step("Lender accepts the request"):
        lender_incoming_request.open_inventory(base_url)
        lender_incoming_request.expect_item_is_reqested_by_lender()
        lender_incoming_request.click_accept_borrowing_request()
        lender_incoming_request.accept_request_modal_opens()
        lender_incoming_request.accept_request_modal_click_agree()

    with allure.step("Borrower confirms pickup"):
        borrower_search_page.open_and_search(base_url, item_name)
        borrower_search_page.expect_request_is_accepted()
        borrower_search_page.click_confirm_pick_up()
        borrower_search_page.confirm_collection_modal_opens()
        borrower_search_page.confirm_collection_modal_click_confirm()

    with allure.step("Lender confirms pickup"):
        lender_lent_item.open_inventory(base_url)
        lender_lent_item.click_confirm_pick_up()
        lender_lent_item.confirm_collection_modal_lender_opens()
        lender_lent_item.confirm_collection_modal_lender_click_confirm()
        lender_lent_item.expect_item_is_collected()

    with allure.step("Lender marks item as returned"):
        lender_lent_item.open_inventory(base_url)
        # The lender's "Confirm returned" button is the CONFIRM_RETURNED action,
        # whose modal is the "confirm-returned" one.
        lender_lent_item.click_confirm_returned_button()
        lender_lent_item.confirm_returned_modal_borrower_opens()
        lender_lent_item.confirm_returned_modal_borrower_click_confirm_returned()

    with allure.step(
        "Item is available again immediately, without borrower confirmation"
    ):
        borrower_search_page.open_and_search(base_url, item_name)
        borrower_search_page.expect_item_is_available()
