import allure
import pytest
from pages.auth_flow import AuthFlow


@pytest.mark.smoke
@pytest.mark.regression
@allure.feature("Authentication")
@allure.title("User can log out successfully")
@allure.severity(allure.severity_level.BLOCKER)
def test_logout(page, base_url, beta_code, user_email, user_password):
    auth = AuthFlow(page)

    with allure.step("Log in"):
        auth.open_base(base_url)
        auth.pass_beta(beta_code)
        auth.open_email_password_login()
        auth.login_with_email_password(user_email, user_password)
        auth.expect_logged_in()

    with allure.step("Open sidebar and click logout"):
        auth.open_sidebar()
        auth.click_logout()

    with allure.step("Verify user is logged out"):
        auth.expect_logged_out()
