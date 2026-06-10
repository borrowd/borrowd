import os
import pathlib
import tempfile

import allure
import pytest
from dotenv import load_dotenv
from pages.auth_flow import AuthFlow
from playwright.sync_api import Browser, Page

load_dotenv()

AUTH_DIR = pathlib.Path(__file__).parent / "tests" / ".auth"


def _maybe_attach_screenshot(
    request: pytest.FixtureRequest, page: Page, name: str
) -> None:
    rep = getattr(request.node, "rep_call", None)
    if rep is not None and rep.failed:
        allure.attach(
            page.screenshot(),
            name=f"Screenshot — {name}",
            attachment_type=allure.attachment_type.PNG,
        )


def _maybe_attach_video(request: pytest.FixtureRequest, page: Page) -> None:
    rep = getattr(request.node, "rep_call", None)
    if page.video is None:
        return
    video_path = pathlib.Path(page.video.path())
    if rep is not None and rep.failed and video_path.exists():
        allure.attach.file(
            str(video_path),
            name="Video",
            attachment_type=allure.attachment_type.WEBM,
        )
    elif video_path.exists():
        video_path.unlink(missing_ok=True)
        try:
            video_path.parent.rmdir()
        except OSError:
            pass


@pytest.fixture(scope="session")
def base_url():
    return os.environ["E2E_BASE_URL"]


@pytest.fixture(scope="session")
def beta_code():
    return os.environ["E2E_BETA_CODE"]


@pytest.fixture(scope="session")
def user_email():
    return os.environ["E2E_USER_EMAIL"]


@pytest.fixture(scope="session")
def user_password():
    return os.environ["E2E_USER_PASSWORD"]


@pytest.fixture(scope="session")
def borrower_email():
    return os.environ["E2E_BORROWER_EMAIL"]


@pytest.fixture(scope="session")
def borrower_password():
    return os.environ["E2E_BORROWER_PASSWORD"]


@pytest.fixture(scope="session")
def lender_email():
    return os.environ["E2E_LENDER_EMAIL"]


@pytest.fixture(scope="session")
def lender_password():
    return os.environ["E2E_LENDER_PASSWORD"]


@pytest.fixture(scope="session")
def user_auth_state(browser: Browser, base_url, beta_code, user_email, user_password):
    """Authenticate once per session; save cookies/localStorage to file."""
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    auth_file = str(AUTH_DIR / "user.json")
    context = browser.new_context()
    page = context.new_page()
    auth = AuthFlow(page)
    auth.open_base(base_url)
    auth.pass_beta(beta_code)
    auth.open_email_password_login()
    auth.login_with_email_password(user_email, user_password)
    auth.expect_logged_in()
    context.storage_state(path=auth_file)
    context.close()
    return auth_file


@pytest.fixture(scope="session")
def borrower_auth_state(
    browser: Browser, base_url, beta_code, borrower_email, borrower_password
):
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    auth_file = str(AUTH_DIR / "borrower.json")
    context = browser.new_context()
    page = context.new_page()
    auth = AuthFlow(page)
    auth.open_base(base_url)
    auth.pass_beta(beta_code)
    auth.open_email_password_login()
    auth.login_with_email_password(borrower_email, borrower_password)
    auth.expect_logged_in()
    context.storage_state(path=auth_file)
    context.close()
    return auth_file


@pytest.fixture(scope="session")
def lender_auth_state(
    browser: Browser, base_url, beta_code, lender_email, lender_password
):
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    auth_file = str(AUTH_DIR / "lender.json")
    context = browser.new_context()
    page = context.new_page()
    auth = AuthFlow(page)
    auth.open_base(base_url)
    auth.pass_beta(beta_code)
    auth.open_email_password_login()
    auth.login_with_email_password(lender_email, lender_password)
    auth.expect_logged_in()
    context.storage_state(path=auth_file)
    context.close()
    return auth_file


@pytest.fixture
def user_page(request: pytest.FixtureRequest, browser: Browser, user_auth_state):
    video_dir = pathlib.Path(tempfile.mkdtemp())
    context = browser.new_context(
        storage_state=user_auth_state,
        record_video_dir=str(video_dir),
    )
    page = context.new_page()
    yield page
    _maybe_attach_screenshot(request, page, "user_page")
    context.close()
    _maybe_attach_video(request, page)


@pytest.fixture
def borrower_page(
    request: pytest.FixtureRequest, browser: Browser, borrower_auth_state
):
    video_dir = pathlib.Path(tempfile.mkdtemp())
    context = browser.new_context(
        storage_state=borrower_auth_state,
        record_video_dir=str(video_dir),
    )
    page = context.new_page()
    yield page
    _maybe_attach_screenshot(request, page, "borrower_page")
    context.close()
    _maybe_attach_video(request, page)


@pytest.fixture
def lender_page(request: pytest.FixtureRequest, browser: Browser, lender_auth_state):
    video_dir = pathlib.Path(tempfile.mkdtemp())
    context = browser.new_context(
        storage_state=lender_auth_state,
        record_video_dir=str(video_dir),
    )
    page = context.new_page()
    yield page
    _maybe_attach_screenshot(request, page, "lender_page")
    context.close()
    _maybe_attach_video(request, page)


@pytest.fixture
def existing_item_name():
    return "E2E TEST BORROW-RETURN ITEM"


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call":
        item.rep_call = rep
