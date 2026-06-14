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
@allure.title("Moderator can delete a group they created")
@allure.severity(allure.severity_level.NORMAL)
def test_moderator_can_delete_group(user_page, base_url):
    group_name = f"E2E {fake.company()[:25]} {datetime.now().strftime('%H%M%S')}"

    with allure.step("Create a group to delete"):
        user_page.goto(f"{base_url}/groups/")
        groups = GroupsPage(user_page)
        groups.expect_opened()
        groups.click_create_group_button()

        create = GroupCreatePage(user_page)
        create.expect_opened()
        create.fill_group_name(group_name)
        create.fill_group_description(fake.text(max_nb_chars=200))
        create.click_create_group_button()

        details = GroupDetails(user_page)
        details.expect_opened()

    with allure.step("Navigate to Edit Group page"):
        details.click_edit_group()

        edit = GroupEditPage(user_page)
        edit.expect_opened()

    with allure.step("Delete the group and confirm"):
        edit.click_delete_group()
        edit.expect_delete_modal_opened()
        edit.confirm_delete()

    with allure.step("Verify redirect to groups list and group is gone"):
        groups.expect_opened()
        groups.expect_group_not_in_list(group_name)
