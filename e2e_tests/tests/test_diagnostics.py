import allure
import pytest


@pytest.mark.regression
@allure.feature("Diagnostics")
@allure.title("Report item and group counts for the shared e2e test account")
@allure.severity(allure.severity_level.MINOR)
def test_report_item_and_group_counts(user_page, base_url):
    """No DB access to the cert environment, so this reads counts straight
    off the UI instead — both the inventory and groups list views render
    every owned item/group with no pagination (see inventory_view and
    GroupListView), so a DOM count here matches the real total. Useful for
    confirming/refuting the O(items owned) group-creation slowness in #527
    without needing direct database access."""
    with allure.step("Count owned items via inventory (Your items toggle)"):
        user_page.goto(f"{base_url}/profile/inventory/")
        your_items_toggle = user_page.get_by_role("switch", name="Your items")
        your_items_toggle.check()
        item_count = user_page.locator("div[id^='item-card-']").count()
        allure.attach(
            str(item_count),
            name="owned_item_count",
            attachment_type=allure.attachment_type.TEXT,
        )

    with allure.step("Count groups via groups list"):
        user_page.goto(f"{base_url}/groups/")
        group_count = (
            user_page.locator("#groups-card-container")
            .first.get_by_role("link")
            .count()
        )
        allure.attach(
            str(group_count),
            name="group_count",
            attachment_type=allure.attachment_type.TEXT,
        )

    print(f"\nowned items: {item_count}\ngroups: {group_count}")
