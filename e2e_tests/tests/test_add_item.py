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
@allure.title("User can add a new item to their inventory")
@allure.severity(allure.severity_level.CRITICAL)
def test_create_item(user_page, base_url):
    item_name = f"E2E {fake.word()[:20]} {datetime.now().strftime('%H%M%S')}"
    description = fake.text(max_nb_chars=200)

    user_page.goto(f"{base_url}/profile/inventory/", wait_until="domcontentloaded")

    inventory = InventoryPage(user_page)
    inventory.expect_opened()
    inventory.click_add_item_button()

    add = AddNewItem(user_page)
    add.expect_opened()
    add.fill_item_name(item_name)
    add.fill_item_description(description)
    add.click_categories_button()
    add.expect_modal_with_categories_opened()

    chosen_categories = add.select_random_categories(
        available=AddNewItem.CATEGORY_OPTIONS,
        min_count=1,
        max_count=3,
    )

    add.upload_photo("tests/assets/item.jpg")
    add.click_add_item_button()

    inventory.expect_opened()
    inventory.click_item_by_name(item_name)

    details = ItemDetails(user_page)
    details.expect_opened()
    details.expect_details(
        name=item_name,
        description=description,
    )
    details.expect_photo_visible(item_name)
    details.expect_categories(chosen_categories)
