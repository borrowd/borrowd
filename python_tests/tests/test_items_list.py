import allure
import pytest
from pages.items_page import ItemsPage


@pytest.mark.smoke
@pytest.mark.regression
@allure.feature("Items")
@allure.title("Items list page loads and search is available")
@allure.severity(allure.severity_level.CRITICAL)
def test_items_list_loads(user_page, base_url):
    user_page.goto(f"{base_url}/items/")
    items = ItemsPage(user_page)
    items.expect_opened()
