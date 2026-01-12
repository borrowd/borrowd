# Contributing

## Dev env setup

This project uses:

* [`uv`](https://docs.astral.sh/uv/)
* [`pre-commit`](https://pre-commit.com/)
* [`vite`](https://vite.dev/)

### 1. Install `uv`, `npm` and other tools

Recommended: install `npm` via
[`nvm`, Node Version Manager](https://github.com/nvm-sh/nvm?tab=readme-ov-file#installing-and-updating):

```
# Python stuff
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install ruff
uv tool install pre-commit

# Javascript stuff
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
# Activate nvm by opening a new terminal or sourcing ~/.nvm/nvm.sh; then:
nvm install stable
nvm use stable  # after this, `which npm` should find a working npm version
```

### 2. Clone repo

Assumes you've got
[`ssh` setup with GitHub](https://docs.github.com/en/authentication/connecting-to-github-with-ssh),
which is advisable. Otherwise, use the http link from the repo
instead.

```
git clone git@github.com:borrowd/borrowd.git && cd borrowd/
```

### 3. Install all dependencies

```
# This will automatically create a local Python virtual environment
# at .venv and setup the git pre-commit hook
uv sync

# This makes it so that the rules defined in .pre-commit-config.yaml
# are automatically executed before a commit can be made. NB you can
# also run them as a standalone command with `uvx pre-commit`.
pre-commit install

# This installs our frontend ecosystem dependencies: vite, its
# tailwind plugin, etc.
npm install
```

### 4. Create local `.env` file

This project uses [`django-environ`](https://pypi.org/project/django-environ/)
to manage env-var based configurability for the app. It expects the
`.env` file to sit in the root of the repository, above the `borrowd/`
Django project directory and the various sibling Django app dirs
(`borrowd_items/`, etc.)

An example `.env` file is included in the repo at `.env.example`.
As part of your setup, copy this to a file named simply`.env`.

```bash
cp .env.example .env
```

The example file contains default values which are appropriate for
local development, but you can tweak the values in your own `.env`
to your liking.

#### Env vars

* `BORROWD_BETA_ENABLED`

_Required: No_
_Default: False_

Specifies whether or not to enable the "Beta Wall". This is functionality
that requires users to have an enter a code before accessing the application,
above and beyond the normal auth process.

* `BORROWD_USE_LOCAL_BUNDLING`

_Required: No_
_Default: False_

Specifies whether or not to use `vite` for local serving of JS/CSS
assets in dev. Also required for prod (where we can't rely on CDNs to
serve our static assets).

* `LOCAL_SENTRY_ENABLED`

_Required: No_
_Default: False_

Specifies whether or not to enable the sentry integration when running locally.
Must be paired with `DJANGO_SETTINGS_MODULE=borrowd.config.dev.django`. This
should only be turned on when debugging the sentry integration itself.

* `DJANGO_SECRET_KEY`

_Required: either this OR the subsequent var_

Long, high-entropy, secret string for Django to use for cryptography
operations.

* `DJANGO_SECRET_KEY_VAR_NAME`

_Required: either this OR the previous var_

An alternative to `DJANGO_SECRET_KEY`. The _name_ of _another_ env
var in which is specified a long, high-entropy, secret string for
Django to use for cryptography operations.

Either this var _or_ `DJANGO_SECRET_KEY` must be set. If this var is
set, then the value of `DJANGO_SECRET_KEY` will be ignored.

* `DJANGO_SETTINGS_MODULE`

_Required: Yes_
_Default: None_

Module path to the desired django config file to load.

### 5. Running the app

Now all your tooling is installed, you're ready to fire up the
Borrow'd app locally.

There are two parts to this:
1. Run the `vite` dev server, for hot reloading local CSS / JS when
   updated, and
2. Run the Django dev server, for serving the app

You may find it most convenient to run these in two separate shell
sessions.

First, the `vite` part. This command, defined in `package.json`,
simply runs the `vite` server, which you installed as a dependency
with `npm install` back in step 3 above.

```
npm run dev
```

Then, the Python part (in a separate shell).

Note that you don't _need_ to `activate` your Python `venv` to do
this; `uv` provides a useful shorthand to automatically make use
of the local `venv`, using its `run` subcommand:

```
uv run manage.py migrate
uv run manage.py loaddata items/item_categories
uv run manage.py runserver
```

At this point, your local Borrow'd checkout should be running at
http://127.0.0.1:8000/.

We are using [`django-vite`](https://pypi.org/project/django-vite/).
This provides a template tag which, in dev mode, injects the
necessary Javascript to connect to the `vite` server we started with
`npm run dev`; that server is what watches our filesystem for changes
requiring updates to JS or CSS (i.e. Tailwind) files. In prod, JS+CSS
dependencies will have been bundled, so that template tag becomes a
no-op.

#### Optional: Authenticating a new user

You need to sign up as a new user with your email address. You can use the + method to subdivide for more than one user (e.g. `test@example.com` and `test+1@example.com` will be two different users).

Emails which would normally be sent to your email in prod will show up in the console, **including login codes**.

#### Optional: load demo data

Demo data is kept outside the repo. We have a custom management
command, `loadborrowddata`, which ensures that signals are disabled
for the loading process.

Example demo data load command:

```
uv run manage.py loadborrowddata fixtures/demo_data.yaml
```

## Working with tools via `uv`

Use the `uvx` command to invoke tools installed via `uv`:

```
uvx ruff format
uvx pre-commit
```

## Repo layout

The Django
[Project](https://docs.djangoproject.com/en/5.2/intro/tutorial01/#creating-a-project)
is in the `borrowd/` directory. Django
[apps](https://docs.djangoproject.com/en/5.2/ref/django-admin/#startapp)
are created to namespace code and assets for different aspects of the
project: users, groups, etc. Note that while the top-level app dirs
are prefixed with `borrowd_`, the model class names therein are not
(e.g. `borrowd_items.models.`**`Item`**, not `BorrowdItem`).

The `templates/` and `static/` dirs are kept at the top level of the
repo.
* The `templates/[components|includes|layouts]/` subdirs contain
  resources used broadly across the project.
* Resources for specific areas are kept in other, namespaced subdirs,
  e.g. `templates/[users|web|etc...]/`.

## Front-end

We do not (currently) use a full frontend framework like React or Vue.

All markup is generated by the backend, mostly using Django's standard
templating system (similar to [Jinja2](https://jinja.palletsprojects.com/en/stable/templates/#synopsis)).

We use [django-cotton](https://django-cotton.com/) to enable creating
reusable UI components.
* Note that instead of the default `templates/cotton/` directory, we
  use the [`COTTON_DIR` config](https://django-cotton.com/docs/configuration)
  to store components in the more sensible `templates/components/` dir.
* Remember that components _can_ live in additional subdirs of
  `templates/components/`: components in subfolders can be referenced
   using dot notation to represent folder levels. See the docs section
   "Subfolders" [on this page](https://django-cotton.com/docs/usage-patterns).
[django-template-partials](https://pypi.org/project/django-template-partials/)
can also help with reuse.

The intention is to use a lightweight Javascript microframework for
declarative interactivity where needed, e.g. [alpine.js](https://alpinejs.dev/)
or [htmx](https://htmx.org/).

We use [TailwindCSS](https://tailwindcss.com/) for styling, rolled-up
and minified by [vite.js](https://vite.dev/).

We also use [DaisyUI](https://daisyui.com/)
for pre-built component styles. See [FigmaDaisyGuidelines.md](docs/FigmaDaisyGuidelines.md) for a walkthrough on how to apply or convert Figma designs to Daisy components in the app.

## Users and Authentication

We use [django-allauth](https://allauth.org/) for authentication. The
few, specific templates we have needed to override are under the
top-level templates folder, at `templates/account/` and `templates/allauth/`.

We have not used a
[custom user model](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/#substituting-a-custom-user-model),
just a related Profile model with a
[one-to-one relationship](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/#extending-the-existing-user-model)
with the standard User model. This is defined in the `borrowd_users/` app.


## Deployment
Configuration files are present to deploy the app on platform.sh.

`.platform.app.yaml` holds app and services configurations as well as deployment hooks
`.env.platform` contains public env vars that will be pushed with the app

Prod media and file storages are configured to use AWS S3 buckets (via wasabi).

Platform.sh maintains a git repository whose branches are each deployed as separate environments with their own services. Environment variables can be configured to be shared across environments. `main` is considered the CI/CD build and tagged git branches will be merged to an official public `release` branch.

To manually push and deploy the app (assuming platform.sh access):
```
platform project:set-remote <project-id>
git push -u platform <main|release|feature-branch>
```

DB CLI
```
platform sql -e main
```

View container logs
```
platform log -p <project-id> -e main
```
