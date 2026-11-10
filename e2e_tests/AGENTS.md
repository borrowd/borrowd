# AGENTS.md — E2E tests (`e2e_tests/`)

Playwright (Python) + pytest browser tests. The root [AGENTS.md](../AGENTS.md) applies here too; this file covers what is specific to this suite. The CI workflows are `.github/workflows/ci.yml` (the `e2e` job) and `.github/workflows/e2e-smoke.yml`.

## Two modes

`E2E_MODE` selects where the suite runs (`conftest.py`):

- **`ephemeral`** — CI's regression job. The app is booted inside the job on a freshly migrated Postgres database seeded by `uv run manage.py seed_e2e_data` (three fixed users plus a group they share). No beta wall, no cleanup sweeps. Credentials default to the seeded accounts.
- **`cert`** (default) — the shared, long-lived cert deployment, reached through `E2E_BASE_URL` with the real accounts in the `E2E_*` variables. The nightly smoke workflow uses it. The cleanup sweeps in `conftest.py` run only here.

A test must work in both modes unless it is marked otherwise. Don't branch on the mode inside a test.

## Writing tests

- **Self-contained.** A test creates what it needs, with unique names (`uuid4` or a timestamp), and finds it by that name. It never depends on pre-existing data or hardcoded IDs, and never calls `pytest.skip` because data is missing. If tests need shared fixtures, add them to `seed_e2e_data`, which must stay idempotent.
- **Markers.** Every test is `@pytest.mark.regression`. Add `@pytest.mark.smoke` only for a journey that touches real infrastructure (auth, media upload, production config), since smoke runs against the shared cert environment; keep that set small.
- **Page objects.** Locators live in `pages/`, not in tests. Prefer role-based locators (`get_by_role`) and scope them by item or group ID wherever a list can hold several (see `SearchPage`, which takes an item ID and a card section). Card and modal ids embed the section name, e.g. `item-card-search-<pk>`.
- **Reading the UI.** The test asserts what a user sees. Don't reach into the database or call internal endpoints to set up state; seed it or drive the UI.

## Covering new functionality

Every new user-facing feature adds or extends a `regression` test in the same PR (the rule and its exceptions are in the root [AGENTS.md](../AGENTS.md)). Aim for one journey per feature that proves a user can complete it, not a test per code path.

- **Extend before adding.** If the feature is a new step in an existing journey, extend that test and its page object. Otherwise add `tests/test_<feature>.py`.
- **Cover the main path plus at most the one failure a user is likely to hit.** Leave edge cases and permission matrices to unit tests.
- **Page object first.** Add locators for the new UI to a page object in `pages/`, then write the test against it.
- **Needs shared data or another user?** Create it through the UI in the test. If it needs standing fixtures, extend `seed_e2e_data` and its tests in `tests/test_seed_e2e_data.py`.
- **Check it can fail.** Break the feature briefly (or assert against the wrong text) and confirm the test goes red before relying on it.
- **Run it locally** in `ephemeral` mode before opening the PR, and say in the PR description which E2E test covers the feature.

## Keeping the suite healthy

- **UI changes break locators.** When a change alters button labels, headings, template structure or a user flow, update the matching page object in the same PR, and run the affected tests locally.
- **Failures.** Read the Allure report and `server.log` (uploaded by the CI job on failure) before changing anything. Don't add reruns, longer timeouts or skips to get green. Fix a real flake, or quarantine the test with a linked issue.
- **Reruns.** `pytest.ini` retries failures; when measuring flakiness, pass `--reruns 0`.
- **Pins.** `playwright` in `requirements.txt` is pinned and must support the Ubuntu image behind `ubuntu-latest`. When bumping it, rerun the whole suite.
- **Blocking status.** The `e2e` job is non-blocking (`continue-on-error`) until the suite has proven stable. Don't remove that without being asked.

## Running locally

Full steps are in [docs/CONTRIBUTING.md](../docs/CONTRIBUTING.md#end-to-end-tests). Run a single test with `E2E_MODE=ephemeral pytest tests/test_login.py --reruns 0` from this directory.
