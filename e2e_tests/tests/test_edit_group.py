from datetime import datetime

import allure
import pytest
from faker import Faker
from pages.group_create_page import GroupCreatePage
from pages.group_details_page import GroupDetails
from pages.group_edit_page import GroupEditPage
from pages.groups_page import GroupsPage

fake = Faker()


@pytest.mark.regression
@allure.feature("Groups")
@allure.title("Moderator can edit group name and description")
@allure.severity(allure.severity_level.NORMAL)
def test_edit_group(user_page, base_url):
    original_name = f"E2E {fake.company()[:25]} {datetime.now().strftime('%H%M%S')}"
    original_description = fake.text(max_nb_chars=200)

    with allure.step("Create a group to edit"):
        user_page.goto(f"{base_url}/groups/")
        groups = GroupsPage(user_page)
        groups.expect_opened()
        groups.click_create_group_button()

        create = GroupCreatePage(user_page)
        create.expect_opened()
        create.fill_group_name(original_name)
        create.fill_group_description(original_description)
        create.click_create_group_button()

        details = GroupDetails(user_page)
        details.expect_opened()

    with allure.step("Navigate to Edit Group page"):
        details.click_edit_group()

        edit = GroupEditPage(user_page)
        edit.expect_opened()

    with allure.step("Update name and description"):
        new_name = (
            f"E2E Edited {fake.company()[:20]} {datetime.now().strftime('%H%M%S')}"
        )
        new_description = fake.text(max_nb_chars=200)

        edit.fill_group_name(new_name)
        edit.fill_group_description(new_description)
        edit.click_save()

    with allure.step("Verify updated details on group page"):
        details.expect_opened()
        details.expect_details(
            name=new_name,
            description=new_description,
        )
