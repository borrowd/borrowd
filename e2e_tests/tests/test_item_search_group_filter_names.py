from uuid import uuid4

import allure
import pytest
from faker import Faker
from pages.group_create_page import GroupCreatePage
from pages.groups_page import GroupsPage
from pages.items_page import ItemsPage
from playwright.sync_api import expect

fake = Faker()


@pytest.mark.regression
@allure.feature("Items")
@allure.title(
    "Group names with quotes or script-breaking characters render inertly in the item search filter"
)
@allure.severity(allure.severity_level.CRITICAL)
def test_item_search_group_filter_handles_unsafe_group_names(user_page, base_url):
    # Group names are embedded in the item search page's Alpine x-data as
    # JS string literals. HTML autoescaping alone doesn't protect that
    # context: the browser decodes entities before Alpine evaluates the
    # expression, so an apostrophe or a crafted payload could break out of
    # the string and run as script (see templates/components/items/filter_form.html).
    quote_name = f"E2E O'Connor's {uuid4().hex[:8]}"
    breakout_name = f"E2E ');window.__e2eXssFired=true;// {uuid4().hex[:8]}"

    groups = GroupsPage(user_page)
    create = GroupCreatePage(user_page)

    with allure.step("Create groups with an apostrophe and a breakout payload"):
        for name in (quote_name, breakout_name):
            user_page.goto(f"{base_url}/groups/")
            groups.expect_opened()
            groups.click_create_group_button()
            create.expect_opened()
            create.fill_group_name(name)
            create.fill_group_description(fake.text(max_nb_chars=100))
            create.click_create_group_button()

    dialogs: list[str] = []
    user_page.on(
        "dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss())
    )

    with allure.step("Open the item search group filter"):
        items = ItemsPage(user_page)
        user_page.goto(f"{base_url}/items/", wait_until="domcontentloaded")
        items.expect_opened()
        items.open_group_filter_modal()

    with allure.step("Both group names render as inert text, not executed script"):
        expect(items.group_filter_chip(quote_name)).to_be_visible()
        expect(items.group_filter_chip(breakout_name)).to_be_visible()
        assert dialogs == []
        assert user_page.evaluate("() => window.__e2eXssFired") is None
