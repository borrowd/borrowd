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

### 4. Django stuff

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
