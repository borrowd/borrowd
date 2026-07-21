import os
import pathlib
import re
import tempfile
import time

import allure
import pytest
from dotenv import load_dotenv
from pages.auth_flow import AuthFlow
from pages.group_details_page import GroupDetails
from pages.inventory_page import InventoryPage
from pages.item_details_page import ItemDetails
from pages.item_edit_page import ItemEditPage
from playwright.sync_api import Browser, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

load_dotenv()

# The shared cert environment can be slow (long POSTs, late Alpine renders);
# Hence, extra timeout
expect.set_options(timeout=30_000)

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


def _delete_e2e_items(page: Page, base_url: str, budget_seconds: float = 600) -> None:
    """Delete generated 'E2E ... <timestamp>' items via the UI so the
    environment's inventory doesn't grow without bound across runs.

    Only items showing the Available banner are attempted: items stuck
    mid-transaction can't be deleted, and each doomed attempt costs the
    full expect timeout. A hard time budget bounds the sweep either way.
    """
    inventory = InventoryPage(page)
    details = ItemDetails(page)
    edit = ItemEditPage(page)
    name_pattern = re.compile(r"^E2E\b.*(?:\d{6}|[0-9a-f]{8})$")
    # Cards are stamped into the DOM by Alpine; wait for any card or the
    # empty state before concluding there are no leftovers.
    cards_rendered = page.locator("div[id^='item-card-']").or_(
        page.get_by_text("You have no items yet.")
    )
    leftover_cards = (
        page.locator("div[id^='item-card-']")
        .filter(has=page.get_by_role("heading", name=name_pattern))
        .filter(has=page.get_by_text("Available", exact=True))
    )
    skipped: set[str] = set()
    deadline = time.monotonic() + budget_seconds

    # Generous timeout: a backlog of leftovers slows this page down. Only
    # navigated here and after a failed delete attempt — a successful delete
    # already redirects back to this exact page (see inventory.expect_opened()
    # below), so re-navigating on every iteration was a pure wasted round trip
    # per item, dominating the whole sweep's wall-clock time.
    def goto_inventory() -> None:
        page.goto(
            f"{base_url}/profile/inventory/",
            wait_until="domcontentloaded",
            timeout=120_000,
        )

    goto_inventory()
    for _ in range(100):
        if time.monotonic() > deadline:
            print("E2E item cleanup stopped: time budget exhausted")
            return
        try:
            cards_rendered.first.wait_for(timeout=30_000)
        except PlaywrightTimeoutError:
            return
        leftover = None
        leftover_name = ""
        for card in leftover_cards.all():
            name = card.get_by_role("heading", name=name_pattern).inner_text().strip()
            if name not in skipped:
                leftover, leftover_name = card, name
                break
        if leftover is None:
            return
        try:
            leftover.get_by_role("heading", name=name_pattern).click()
            details.click_edit()
            edit.click_delete_item()
            edit.expect_delete_modal_opened()
            edit.confirm_delete()
            inventory.expect_opened()
        except Exception:
            # Safety net so one bad item can't loop the sweep forever. The
            # page may be in an unknown state after a failed attempt, so
            # force a fresh navigation before the next iteration.
            skipped.add(leftover_name)
            goto_inventory()


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


def _delete_e2e_groups(page: Page, base_url: str, budget_seconds: float = 300) -> None:
    """Leave (and thereby delete) generated 'E2E ... <timestamp>' groups via
    the UI so the environment's group list doesn't grow without bound across
    runs.

    Unlike items, groups have no dedicated delete flow — leaving as the sole
    active member is the only way to remove one (LeaveGroupView.post deletes
    a group once it has no remaining active members). Since this cleanup
    never existed before, the first few runs may hit the time budget before
    draining a large historical backlog; the skip set + budget bound each
    run's cost regardless of backlog size.
    """
    details = GroupDetails(page)
    name_pattern = re.compile(r"^E2E\b.*(?:\d{6}|[0-9a-f]{8})$")
    # #groups-card-container is (harmlessly) duplicated in the DOM: the
    # group_list.html wrapper and the group_list_card.html partial it
    # includes both carry the same id (an hx-swap="outerHTML" target that
    # ends up nested rather than replaced on a plain server render). .first
    # still contains everything the inner one does, since it wraps it.
    container = page.locator("#groups-card-container").first
    leftover_links = container.get_by_role("link", name=name_pattern)
    skipped: set[str] = set()
    deadline = time.monotonic() + budget_seconds

    def goto_groups() -> None:
        page.goto(f"{base_url}/groups/", wait_until="domcontentloaded", timeout=120_000)

    goto_groups()
    for _ in range(100):
        if time.monotonic() > deadline:
            print("E2E group cleanup stopped: time budget exhausted")
            return
        try:
            container.wait_for(timeout=30_000)
        except PlaywrightTimeoutError:
            return
        leftover_name = None
        for link in leftover_links.all():
            name = link.inner_text().strip()
            if name not in skipped:
                leftover_name = name
                break
        if leftover_name is None:
            return
        try:
            container.get_by_role("link", name=leftover_name, exact=True).click()
            details.expect_opened()
            details.leave_group_as_sole_moderator()
            expect(page).to_have_url(re.compile(r"/groups/?$"))
        except Exception:
            # Safety net so one bad group can't loop the sweep forever. The
            # page may be in an unknown state after a failed attempt, so
            # force a fresh navigation before the next iteration.
            skipped.add(leftover_name)
            goto_groups()


@pytest.fixture(scope="session", autouse=True)
def cleanup_e2e_groups(browser: Browser, base_url, user_auth_state):
    def sweep() -> None:
        context = browser.new_context(storage_state=user_auth_state)
        page = context.new_page()
        try:
            _delete_e2e_groups(page, base_url)
        except Exception as exc:  # best-effort: never fail the run on cleanup
            print(f"E2E group cleanup skipped: {exc}")
        finally:
            context.close()

    sweep()
    yield
    sweep()
