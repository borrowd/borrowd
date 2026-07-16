import os
import pathlib
import re
import tempfile

import allure
import pytest
from dotenv import load_dotenv
from pages.auth_flow import AuthFlow
from pages.inventory_page import InventoryPage
from pages.item_details_page import ItemDetails
from pages.item_edit_page import ItemEditPage
from playwright.sync_api import Browser, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

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


def _delete_e2e_items(page: Page, base_url: str) -> None:
    """Delete generated 'E2E ... <timestamp>' items via the UI so the
    environment's inventory doesn't grow without bound across runs.
    """
    inventory = InventoryPage(page)
    details = ItemDetails(page)
    edit = ItemEditPage(page)
    name_pattern = re.compile(r"^E2E\b.*\d{6}$")
    undeletable: set[str] = set()

    for _ in range(100):
        # Generous timeout: a backlog of leftovers slows this page down.
        page.goto(
            f"{base_url}/profile/inventory/",
            wait_until="domcontentloaded",
            timeout=120_000,
        )
        headings = page.get_by_role("heading", name=name_pattern)
        try:
            headings.first.wait_for(timeout=10_000)
        except PlaywrightTimeoutError:
            return
        leftover = None
        leftover_name = ""
        for heading in headings.all():
            name = heading.inner_text().strip()
            if name not in undeletable:
                leftover, leftover_name = heading, name
                break
        if leftover is None:
            return
        try:
            leftover.click()
            details.click_edit()
            edit.click_delete_item()
            edit.expect_delete_modal_opened()
            edit.confirm_delete()
            inventory.expect_opened()
        except Exception:
            # Items stuck mid-transaction can't be deleted; skip them so one
            # bad item doesn't block the rest of the sweep.
            undeletable.add(leftover_name)


@pytest.fixture(scope="session", autouse=True)
def cleanup_e2e_items(browser: Browser, base_url, user_auth_state):
    def sweep() -> None:
        context = browser.new_context(storage_state=user_auth_state)
        page = context.new_page()
        try:
            _delete_e2e_items(page, base_url)
        except Exception as exc:  # best-effort: never fail the run on cleanup
            print(f"E2E item cleanup skipped: {exc}")
        finally:
            context.close()

    # Sweep before the run too: a failed run skips its own cleanup, and the
    # leftovers slow the inventory page down for every run after it.
    sweep()
    yield
    sweep()
