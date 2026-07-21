from uuid import uuid4

import allure
import pytest
from faker import Faker
from pages.group_create_page import GroupCreatePage
from pages.group_details_page import GroupDetails
from pages.group_invite_page import GroupInvitePage
from pages.groups_page import GroupsPage

fake = Faker()


@pytest.mark.smoke
@pytest.mark.regression
@allure.feature("Groups")
@allure.title("Moderator can generate an invite link for their group")
@allure.severity(allure.severity_level.CRITICAL)
def test_group_invite_link(user_page, base_url):
    group_name = f"E2E {fake.company()[:25]} {uuid4().hex[:8]}"

    with allure.step("Create a group"):
        user_page.goto(f"{base_url}/groups/")
        groups = GroupsPage(user_page)
        groups.expect_opened()
        groups.click_create_group_button()

        create = GroupCreatePage(user_page)
        create.expect_opened()
        create.fill_group_name(group_name)
        create.fill_group_description(fake.text(max_nb_chars=200))
        create.click_create_group_button()

    with allure.step("Open group detail page"):
        user_page.goto(f"{base_url}/groups/")
        groups.expect_opened()
        groups.click_group_by_name(group_name)

        details = GroupDetails(user_page)
        details.expect_opened()

    with allure.step("Navigate to invite link page"):
        details.click_get_invite_link()

        invite = GroupInvitePage(user_page)
        invite.expect_opened()

    with allure.step("Verify group name, QR code, and invite URL are shown"):
        invite.expect_group_name(group_name)
        invite.expect_join_link_not_empty()
