from datetime import datetime

import allure
import pytest
from faker import Faker
from pages.inventory_page import InventoryPage
from pages.item_add_new_page import AddNewItem
from pages.item_details_page import ItemDetails

fake = Faker()


@pytest.mark.smoke
@pytest.mark.regression
@allure.feature("Items")
@allure.title("User can create an item and see it in inventory")
@allure.severity(allure.severity_level.CRITICAL)
def test_item_detail_loads(user_page, base_url):
    item_name = f"E2E {fake.word()[:20]} {datetime.now().strftime('%H%M%S')}"
    description = fake.text(max_nb_chars=200)

    with allure.step("Create a new item"):
        user_page.goto(f"{base_url}/profile/inventory/", wait_until="domcontentloaded")
        inventory = InventoryPage(user_page)
        inventory.expect_opened()
        inventory.click_add_item_button()

        add = AddNewItem(user_page)
        add.expect_opened()
        add.fill_item_name(item_name)
        add.fill_item_description(description)
        add.click_categories_button()
        add.select_random_categories(available=["Other"], min_count=1, max_count=1)
        add.click_add_item_button()

    with allure.step("Verify item appears in inventory"):
        inventory.expect_opened()
        inventory.click_item_by_name(item_name)

    with allure.step("Verify item detail page loads"):
        details = ItemDetails(user_page)
        details.expect_opened()
        details.expect_details(
        )
