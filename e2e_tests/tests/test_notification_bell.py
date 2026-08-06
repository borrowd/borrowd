import allure
import pytest
from pages.notification_bell_page import NotificationBellPage


@pytest.mark.smoke
@pytest.mark.regression
@allure.feature("Notifications")
@allure.title("Notification bell opens a popup with recent notifications")
@allure.severity(allure.severity_level.NORMAL)
def test_bell_opens_popup(user_page, base_url):
    with allure.step("Navigate to an authenticated page"):
        user_page.goto(f"{base_url}/items/", wait_until="domcontentloaded")

    with allure.step("Open the notification popup"):
        bell = NotificationBellPage(user_page)
        bell.open()

    with allure.step("Popup shows notifications or the empty state"):
        bell.expect_popup_has_content_or_empty_state()


@pytest.mark.regression
@allure.feature("Notifications")
@allure.title("'View all' in the popup navigates to the notification inbox")
@allure.severity(allure.severity_level.NORMAL)
def test_popup_view_all_navigates_to_inbox(user_page, base_url):
    with allure.step("Open the notification popup"):
        user_page.goto(f"{base_url}/items/", wait_until="domcontentloaded")
        bell = NotificationBellPage(user_page)
        bell.open()

    with allure.step("Click 'View all' and land on the inbox page"):
        bell.click_view_all()


@pytest.mark.regression
@allure.feature("Notifications")
@allure.title("Unread badge does not duplicate on the 30s htmx poll")
@allure.severity(allure.severity_level.NORMAL)
def test_unread_badge_does_not_duplicate_on_poll(user_page, base_url):
    """Regression test for a bug where the badge's htmx poll selected two
    elements with the same id from the full inbox-page response (the
    navbar's own badge and the inbox page's inline badge) and swapped both
    in, doubling the badge. Both now use distinct ids so only one is ever
    matched.
    """
    with allure.step("Navigate to an authenticated page"):
        user_page.goto(f"{base_url}/items/", wait_until="domcontentloaded")

    bell = NotificationBellPage(user_page)
    if bell.badge.count() == 0:
        pytest.skip("Test account has no unread notifications to show a badge for")

    with allure.step("Badge renders once before the poll fires"):
        assert bell.badge.count() == 1

    with allure.step("Wait past the 30s htmx poll interval"):
        user_page.wait_for_timeout(32_000)

    with allure.step("Badge still renders exactly once after polling"):
        assert bell.badge.count() == 1
