from datetime import datetime

import allure
import pytest
from faker import Faker
from pages.group_create_page import GroupCreatePage
from pages.group_details_page import GroupDetails
from pages.groups_page import GroupsPage

fake = Faker()


@pytest.mark.smoke
@pytest.mark.regression
@allure.feature("Groups")
@allure.title("User can create a group and see it in the groups list")
@allure.severity(allure.severity_level.CRITICAL)
def test_group_detail_loads(user_page, base_url):
    group_name = f"E2E {fake.company()[:25]} {datetime.now().strftime('%H%M%S')}"
    description = fake.text(max_nb_chars=200)

    with allure.step("Create a new group"):
        user_page.goto(f"{base_url}/groups/")
        groups = GroupsPage(user_page)
        groups.expect_opened()
        groups.click_create_group_button()

        create = GroupCreatePage(user_page)
        create.expect_opened()
        create.fill_group_name(group_name)
        create.fill_group_description(description)
        create.click_create_group_button()

    with allure.step("Navigate to groups list and verify group appears"):
        user_page.goto(f"{base_url}/groups/")
        groups.expect_opened()
        groups.expect_group_in_list(group_name)

    with allure.step("Open group detail page"):
        groups.click_group_by_name(group_name)

        details = GroupDetails(user_page)
        details.expect_opened()
        details.expect_details(name=group_name, description=description)
