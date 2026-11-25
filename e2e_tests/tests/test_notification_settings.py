import allure
import pytest
from pages.notification_settings_page import NotificationSettingsPage
from playwright.sync_api import expect


@pytest.mark.regression
@allure.feature("Notifications")
@allure.title("A notification category row can be expanded and its email switched off")
@allure.severity(allure.severity_level.NORMAL)
def test_category_row_disclosure_and_email_switch(user_page, base_url):
    settings = NotificationSettingsPage(user_page)

    with allure.step("Open notification settings"):
        settings.open(base_url)

    with allure.step("Expand 'What's included' for Your groups"):
        button = settings.included_button("groups")
        expect(button).to_have_attribute("aria-expanded", "false")
        button.click()
        expect(button).to_have_attribute("aria-expanded", "true")
        expect(settings.included_list("groups")).to_contain_text(
            "Someone joined a group you're in"
        )

    email = settings.switch("Your groups", "Email")
    try:
        with allure.step("Switch email off for Your groups and reload"):
            settings.set_switch("Your groups", "Email", on=False)
            settings.open(base_url)
            expect(email).not_to_be_checked()

        with allure.step("Switch email back on and reload"):
            settings.set_switch("Your groups", "Email", on=True)
            settings.open(base_url)
            expect(email).to_be_checked()
    finally:
        # The cert account is shared across runs; leave it as it was found.
        if not email.is_checked():
            settings.set_switch("Your groups", "Email", on=True)
