from datetime import datetime

import allure
import pytest
from faker import Faker
from pages.inventory_page import InventoryPage
from pages.item_add_new_page import AddNewItem
from pages.item_details_page import ItemDetails
from pages.item_edit_page import ItemEditPage

fake = Faker()


@pytest.mark.regression
@allure.feature("Items")
@allure.title("User can edit item name and description")
@allure.severity(allure.severity_level.NORMAL)
def test_edit_item(user_page, base_url):
    item_name = f"E2E {fake.word()[:20]} {datetime.now().strftime('%H%M%S')}"
    updated_name = f"E2E updated {fake.word()[:15]} {datetime.now().strftime('%H%M%S')}"
    updated_description = fake.text(max_nb_chars=200)

    with allure.step("Create a new item"):
        user_page.goto(f"{base_url}/profile/inventory/", wait_until="domcontentloaded")
        inventory = InventoryPage(user_page)
        inventory.expect_opened()
        inventory.click_add_item_button()

        add = AddNewItem(user_page)
        add.expect_opened()
        add.fill_item_name(item_name)
        add.fill_item_description(fake.text(max_nb_chars=200))
        add.click_categories_button()
        add.select_random_categories(available=["Other"], min_count=1, max_count=1)
        chosen_trust = add.choose_random_trust_level()
        add.click_add_item_button()

        inventory.expect_opened()
        inventory.click_item_by_name(item_name)

    with allure.step("Navigate to Edit item page"):
        details = ItemDetails(user_page)
        details.expect_opened()
        details.click_edit()

        edit = ItemEditPage(user_page)
        edit.expect_opened()

    with allure.step("Update name and description"):
        edit.fill_name(updated_name)
        edit.fill_description(updated_description)
        edit.click_save()

    with allure.step("Verify detail page shows updated values"):
        details.expect_opened()
        details.expect_details(
            name=updated_name,
            description=updated_description,
            trust_value=chosen_trust,
        )
