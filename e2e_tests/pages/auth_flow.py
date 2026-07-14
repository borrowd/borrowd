import re
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect


class AuthFlow:
    def __init__(self, page: Page):
        self.page = page
        self.beta_code_input = page.get_by_role("textbox", name="Code:")
        self.beta_enter_button = page.get_by_role("button", name="Enter beta code")
        self.sign_in_link = page.get_by_role("link", name="Log In")
        self.email_input = page.get_by_role("textbox", name="Email")
        self.password_input = page.get_by_role("textbox", name="Password")
        self.submit_button = page.get_by_role(
            "button", name=re.compile("sign in|log in|login", re.I)
        ).first
        self.hamburger_button = page.locator("label[for='main-drawer']").first
        self.logout_button = page.get_by_role("button", name="Logout")

    def open_base(self, base_url):
        #  for when there's a connection issue due to cold starts or something else
        delays = (5, 10, 15)
        for attempt, delay in enumerate(delays):
            try:
                self.page.goto(base_url)
                return
            except PlaywrightError as error:
                message = str(error)
                transient = (
                    "ERR_CONNECTION" in message or "ERR_EMPTY_RESPONSE" in message
                )
                if not transient:
                    raise
                time.sleep(delay)
                if attempt == len(delays) - 1:
                    raise

    def pass_beta(self, beta_code):
        expect(self.beta_code_input).to_be_visible()
        self.beta_code_input.fill(beta_code)
        expect(self.beta_enter_button).to_be_visible()

        with self.page.expect_navigation():
            self.beta_enter_button.click()

        expect(self.sign_in_link).to_be_visible()

    def open_email_password_login(self):
        expect(self.sign_in_link).to_be_visible()
        close_sidebar = self.page.get_by_role(
            "checkbox", name=re.compile("close sidebar", re.I)
        )
        if close_sidebar.is_visible():
            close_sidebar.click()
        self.sign_in_link.click()

    def login_with_email_password(self, email, password):
        expect(self.email_input).to_be_visible()
        expect(self.password_input).to_be_visible()
        self.email_input.fill(email)
        self.password_input.fill(password)
        expect(self.submit_button).to_be_visible()
        self.submit_button.click()

    def open_sidebar(self):
        expect(self.hamburger_button).to_be_visible()
        self.hamburger_button.click()

    def click_logout(self):
        expect(self.logout_button).to_be_visible()
        self.logout_button.click()

    def expect_logged_in(self):
        expect(self.page).to_have_url(re.compile(r"/items/?$"))

    def expect_logged_out(self):
        expect(self.sign_in_link).to_be_visible()

    def save_state(self, file_path):
        self.page.context.storage_state(path=file_path)
