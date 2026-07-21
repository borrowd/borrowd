from uuid import uuid4

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
@allure.title("User can create a new group and become its moderator")
@allure.severity(allure.severity_level.CRITICAL)
def test_create_group(user_page, base_url):
    group_name = f"E2E {fake.company()[:25]} {uuid4().hex[:8]}"
    description = fake.text(max_nb_chars=200)

    user_page.goto(f"{base_url}/groups/")

    groups = GroupsPage(user_page)
    groups.expect_opened()
    groups.click_create_group_button()

    create = GroupCreatePage(user_page)
    create.expect_opened()
    create.fill_group_name(group_name)
    create.fill_group_description(description)
    create.set_approval_checkbox(True)
    create.upload_banner("tests/assets/group_banner.png")

    create.click_create_group_button()

    details = GroupDetails(user_page)
    details.expect_opened()
    details.expect_details(name=group_name, description=description)
    details.expect_members_count(1)
    details.expect_you_are_moderator()
