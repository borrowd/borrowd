# Contributing

## Dev env setup

This project uses [`uv`](https://docs.astral.sh/uv/) and
[`pre-commit`](https://pre-commit.com/).

### 1. Install `uv` and tools

```
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install ruff
uv tool install pre-commit
```

### 2. Clone repo

```
git clone git@github.com:borrowd/borrowd.git && cd borrowd/
```

### 3. Install all dependencies

```
# This will automatically create a local Python virtual environment
# at .venv
uv sync
```

### 4. Create local `.env` file

This project uses [`django-environ`](https://pypi.org/project/django-environ/)
to manage env-var based configurability for the app. It expects the
`.env` file to sit in the root of the repository, above the `borrowd/`
Django project directory and the various sibling Django app dirs
(`borrowd_web/`, etc.)

An example `.env` file is included in the repo at `.env.example`.
As part of your setup, copy this to `.env`; it contains values which
are appropriate for local development.

```bash
cp .env.example .env
```

### 5. Django stuff

Now all your tooling is installed, you're ready to fire up the
Borrow'd app locally.

Note that you don't _need_ to `activate` your Python `venv` to do
this; `uv` provides a useful shorthand to automatically make use
of the local `venv`, using its `run` subcommand:

```
uv run manage.py migrate
uv run manage.py runserver
```

At this point, your local Borrow'd checkout should be running at
http://127.0.0.1:8000/.

## Working with tools via `uv`

Use the `uvx` command to invoke tools installed via `uv`:

```
uvx ruff format
uvx pre-commit
```
