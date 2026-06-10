import allure
import pytest
from pages.groups_page import GroupsPage


@pytest.mark.smoke
@pytest.mark.regression
@allure.feature("Groups")
@allure.title("Groups list page loads and displays correctly")
@allure.severity(allure.severity_level.CRITICAL)
def test_groups_list_loads(user_page, base_url):
    with allure.step("Navigate to groups list"):
        user_page.goto(f"{base_url}/groups/")

    with allure.step("Verify page elements are visible"):
        groups = GroupsPage(user_page)
        groups.expect_opened()
