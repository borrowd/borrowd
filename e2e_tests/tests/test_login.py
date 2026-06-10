import allure
import pytest
from pages.auth_flow import AuthFlow


@pytest.mark.smoke
@pytest.mark.regression
@allure.feature("Authentication")
@allure.title("User can log in with email and password")
@allure.severity(allure.severity_level.BLOCKER)
def test_user_can_log_in(page, base_url, beta_code, user_email, user_password):
    auth = AuthFlow(page)
    auth.open_base(base_url)
    auth.pass_beta(beta_code)
    auth.open_email_password_login()
    auth.login_with_email_password(user_email, user_password)
    auth.expect_logged_in()
