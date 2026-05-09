# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Borrow'd is a Django 5.2 web application (Python 3.13+) for peer-to-peer item lending within trusted groups. Users can share items with group members based on configurable trust levels.

For full setup walkthrough and deployment notes, see [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).

## Development Commands

### Setup
```bash
uv sync                    # Install Python dependencies (creates .venv)
pre-commit install         # Setup pre-commit hooks
npm install                # Install JS dependencies (vite, tailwind, daisyui)
cp .env.example .env       # Create local env file
```

### Running the App
Run these in separate terminals:
```bash
npm run dev                                       # Vite dev server (hot reload CSS/JS)
uv run manage.py migrate                          # Apply migrations
uv run manage.py loaddata items/item_categories   # Load ItemCategory fixture
uv run manage.py runserver                        # Django dev server at http://127.0.0.1:8000/
```

Optional: load demo data with the custom command (signals are disabled during load):
```bash
uv run manage.py loadborrowddata fixtures/demo_data.yaml
```

### Testing
```bash
uv run manage.py test                              # Run all tests
uv run manage.py test tests.test_borrowing_flows   # Run a specific test module
uv run manage.py test borrowd_groups               # Run an app's tests
```
Tests live both at the repo root (`tests/`, for cross-app flows) and inside individual app directories.

### Code Quality
```bash
uvx ruff format                 # Format code
uvx ruff check --fix            # Lint and auto-fix
uvx djlint templates --reformat # Reformat Django templates
uvx pre-commit run --all-files  # Run all pre-commit hooks
```

Pre-commit hooks (see `.pre-commit-config.yaml`):
- `uv-lock` / `uv-export` — keep lockfile and `requirements.txt` in sync
- `mypy --strict` with `django-stubs` (Python 3.13)
- `ruff` linter, import sort (`I`), and formatter
- `djlint` for templates under `templates/**/*.html`
- Standard hygiene: trailing whitespace, end-of-file fixer, JSON/YAML/TOML checks, etc.

Repo-local `PostToolUse` hooks (configured in `.claude/settings.json`, scripts in `.claude/hooks/`) auto-format edited files to mirror the **formatting** steps from pre-commit (linting and type-checking are NOT auto-applied — rely on pre-commit / IDE for those):
- `format-python.sh` — `ruff check --select I --fix` (import sort) + `ruff format` on `.py` files.
- `format-html.sh` — `djlint --reformat` on `.html` files.

## Architecture

### Django Project Structure
- `borrowd/` — Django project config (settings in `config/`, URL routing, custom `manage.py` commands under `management/commands/`)
- `borrowd_users/` — `BorrowdUser` (extends `AbstractUser`), `Profile`, `SearchTerm` (search-history logging)
- `borrowd_groups/` — `BorrowdGroup`, `Membership` (with trust level + lifecycle status)
- `borrowd_items/` — `Item`, `ItemCategory`, `ItemPhoto`, `Transaction`, `AvailabilitySubscription`
- `borrowd_notifications/` — Notification services on top of `django-notifications-hq`
- `borrowd_beta/` — Beta-access wall (middleware, signup form, allowlist)
- `borrowd_permissions/` — Object-level permission enums (`ItemOLP`, `BorrowdGroupOLP`) and view mixins (`LoginOr403PermissionMixin`, `LoginOr404PermissionMixin`)
- `borrowd_web/` — Landing pages and shared web bits (favicon, etc.)

### Key Domain Concepts

**TrustLevel** (`borrowd/models.py`): `STANDARD`, `HIGH` — controls item visibility between group members. Users set their trust level per-group; items declare a `trust_level_required` for borrowing.

**Item state** (`borrowd_items/models.py`):
- `ItemStatus`: `AVAILABLE`, `REQUESTED`, `RESERVED`, `BORROWED` (tracked on `Item.status`).
- `ItemAction` enum drives state changes — `REQUEST_ITEM`, `ACCEPT_REQUEST`, `REJECT_REQUEST`, `MARK_COLLECTED`, `CONFIRM_COLLECTED`, `MARK_RETURNED`, `CONFIRM_RETURNED`, `CANCEL_REQUEST`, `NOTIFY_WHEN_AVAILABLE`, `CANCEL_NOTIFICATION_REQUEST`.
- `Item.get_actions_for(user)` → tuple of valid next actions.
- `Item.get_action_context_for(user)` → `ItemActionContext(actions, status_text)` — preferred when the view also needs user-facing copy.
- `Item.process_action(user, action)` advances the state machine; raises `InvalidItemAction` / `ItemAlreadyRequested` on misuse.

**Transaction state machine** (`borrowd_items/models.py`):
- States: `REQUESTED` → (`ACCEPTED` | `REJECTED` | `CANCELLED`) → `COLLECTION_ASSERTED` → `COLLECTED` → `RETURN_ASSERTED` → `RETURNED`.
- Both parties must confirm collection and return (dual confirmation): the same user can't both assert and confirm.
- Convention: `party1` is the lender/owner/giver; `party2` is the borrower/receiver.
- Helpers: `Transaction.get_requested_status_transactions_for_user`, `get_active_borrows_for_user`, `get_active_lends_for_user`.

**AvailabilitySubscription**: when an item is `BORROWED`/`RESERVED`, non-owners can subscribe via `NOTIFY_WHEN_AVAILABLE` to be notified when it's available again. A `UniqueConstraint` enforces one active subscription per (user, item).

**Membership lifecycle** (`borrowd_groups/models.py`): `MembershipStatus` is `PENDING`, `ACTIVE`, `SUSPENDED`, `BANNED`, `ENDED`. Groups with `membership_requires_approval=True` create new memberships in `PENDING` until a moderator approves. `BorrowdGroup.objects.create()` is overridden to smuggle a `trust_level` kwarg through to the post-save signal that creates the creator's `Membership`.

**Object-Level Permissions**: uses `django-guardian`. OLP enum values live in `borrowd_permissions/models.py` (`ItemOLP.VIEW = "view_this_item"`, etc.). The `*_this_*` naming convention distinguishes object-level perms (`view_this_item`) from model-level perms (`view_item`). Apply `LoginOr403PermissionMixin` / `LoginOr404PermissionMixin` (from `borrowd_permissions.mixins`) to class-based views — anonymous users get redirected to login, authenticated users without permission get 403/404 respectively. `AnonymousUser` is disabled (`ANONYMOUS_USER_NAME = None`).

**Audit & soft-delete pattern**: most models include `created_by`, `created_at`, `updated_by`, `updated_at`, `deleted_at`, `deleted_by`. A non-null `deleted_at` indicates a soft-deleted record. Don't use raw `.delete()` on these unless you mean a hard delete — set `deleted_at`/`deleted_by` instead.

**System user**: `borrowd_users.system.get_system_user()` returns the user with username `"system"`, used as `created_by` / `updated_by` for actions not initiated by a real user.

### Frontend
- Server-rendered Django templates; **django-cotton** components live in `templates/components/` (configured via `COTTON_DIR = "components"`). Subfolder components are referenced with dot notation. `django-cotton` is pinned at `2.1.2` because newer versions break debug mode.
- **TailwindCSS** + **DaisyUI** via **Vite** (`@tailwindcss/vite`); see `docs/FigmaDaisyGuidelines.md` for converting Figma designs to Daisy components.
- **django-vite** wires the Vite dev server (hot reload) and the production manifest at `build/manifest.json`.
- **alpine.js** and **htmx** (loaded via CDN in `templates/base.html`) for lightweight interactivity; no React/Vue.
- **django-imagekit** does on-upload resizing/thumbnailing (`ProcessedImageField`, `ImageSpecField`) — see `Item.photos`, `Profile.image`, `BorrowdGroup.logo/banner`.
- **django-cleanup** auto-removes orphaned media files when models are deleted.

### Settings
Config uses **django-environ** (loader at `borrowd/config/env.py`). Hierarchy:
- `borrowd/config/base.py` — base settings
- `borrowd/config/dev/django.py` — development (DEBUG default on; toggleable via `DEBUG` env var)
- `borrowd/config/prod/django.py` — production (platform.sh, Postgres, S3/Wasabi storage)
- `borrowd/config/cert/django.py` — certification (pre-prod) environment on platform.sh

Pick the active config via `DJANGO_SETTINGS_MODULE`, e.g. `borrowd.config.dev.django`.

Key env vars (see `docs/CONTRIBUTING.md` for full list):
- `DJANGO_SETTINGS_MODULE` (required)
- `DJANGO_SECRET_KEY` *or* `DJANGO_SECRET_KEY_VAR_NAME` (one is required)
- `BORROWD_BETA_ENABLED` (default `False`) — gates the app behind the beta wall
- `LOCAL_SENTRY_ENABLED` (default `False`) — only flip on when debugging the Sentry integration locally
- `DJANGO_LOG_LEVEL` (default `INFO`)
- Platform.sh injects `PLATFORM_*` vars in prod (DB relationship, app dir, project entropy, etc.)

### Auth
Uses **django-allauth** with email-based login. Login methods include passwordless **login-by-code** (6-digit numeric). Custom pieces:
- Signup view at `/signup/` (`CustomSignupView`); `/accounts/signup/` redirects to it (preserving the `next` query string).
- `BorrowdAccountAdapter` (`borrowd_users.adapters`) is the allauth adapter.
- `CustomPasswordChangeView` overrides allauth's change-password to use `SetPasswordForm` (no current-password prompt — UX call, not security; documented inline in `base.py`).
- `Profile` is created from a post-save signal on `BorrowdUser`.
- `AUTHENTICATION_BACKENDS`: `ModelBackend`, allauth's backend, and guardian's `ObjectPermissionBackend`.

### Storage & infrastructure
- **Local**: SQLite (`db.sqlite3`); media on local filesystem (`MEDIA_ROOT`).
- **Production** (platform.sh): PostgreSQL via the `db` relationship; media on S3 (Wasabi-hosted) via `django-storages`; static via `StaticFilesStorage`.
- **Sentry** is initialized in dev (only when `LOCAL_SENTRY_ENABLED=True`) and always in prod.
- Custom error routing: `handler403 = "borrowd.views.custom_403_router"`; templates `403.html`, `404.html`, `500.html` live in `templates/`.

## Coding Standards

### Type Annotations
All public functions are type-hinted; pre-commit runs `mypy --strict` with `django-stubs`. Use the `Self`, `Never`, `QuerySet["X"]`, and `ForeignKey[X]` patterns already established throughout the codebase.

### Comments
Evergreen comments only — describe current state, not evolution. Don't reference past PRs, removed code, or "added for X" context.

### Naming Conventions
- **Evergreen names**: Choose names that won't need updating
  - ❌ `new_transaction_flow`, `updated_permission_check`
  - ✅ `transaction_flow`, `permission_check`
- **Descriptive names**: Be explicit about purpose
  - ❌ `proc_action`, `get_txn`
  - ✅ `process_action`, `get_current_transaction`
- **Consistency**: Use same terminology throughout codebase
  - Always "Transaction" not "Loan" or "Borrow"
  - Always "BorrowdGroup" not "Community" or "Circle"
  - Always "Item" not "Object" or "Thing"

### Error Handling
Domain-specific exceptions live in `<app>/exceptions.py`, all subclassing `BorrowdException` (`borrowd/exceptions.py`). Raise early on invalid state; surface user-facing failures via Django's messages framework.

## Code Intelligence

Prefer LSP over Grep/Glob/Read for code navigation:
- hover — type info / docs at a position
- goToDefinition — jump to where a symbol is defined
- goToImplementation — find implementations of an abstract method/interface
- findReferences — all usages of a symbol across the codebase
- documentSymbol — list all symbols (classes, functions, variables) in a file
- workspaceSymbol — search for symbols across the entire workspace
- prepareCallHierarchy — get call hierarchy for a function/method
- incomingCalls — find all callers of a function
- outgoingCalls — find all functions called by a function

Before renaming or changing a function signature, use `findReferences` to find all call sites first.

Use Grep/Glob only for text/pattern searches (comments, strings, config values) where LSP doesn't help.

After writing or editing code, check LSP diagnostics and fix any errors before moving on.
