# Worktrees for PR code

Shared by the PR skills. Run from the repo root. `.worktrees/` is gitignored.

## Remote and base

The PR lives in the base repo, which is usually `origin`; in a fork clone it is
often `upstream`. Use the remote whose URL matches the PR's repo
(`git remote -v`; the repo name is in the `pr_feedback.sh` output). Below,
`<remote>` means that remote.

Fetch the base as well as the head, since the base may be stale or, for a
stacked PR, a feature branch that was never fetched:

```bash
git fetch <remote> <baseRefName> pull/<n>/head
```

`FETCH_HEAD` then names the PR head, and `<remote>/<baseRefName>` the base.
Diff the PR with `git diff <remote>/<baseRefName>...<head>`, ignoring merge
commits when comparing against an earlier head.

`gh pr diff <n>` is fine for most PRs but fails (HTTP 406) on very large ones;
use `git diff` in a worktree instead.

## Read-only worktrees (review)

Detached at the PR head, one per reviewer:

```bash
git worktree add --detach .worktrees/pr-<n>-review-<a|b|c> FETCH_HEAD
```

Use the suffix `followup` for a single re-review checkout
(`.worktrees/pr-<n>-followup`). If the path already exists, remove it when it
is a stale checkout of this skill's; otherwise pick another suffix. Never reuse
one with uncommitted changes.

Fresh worktrees have no virtualenv, `.env` or database, and agents must not
read `.env`. Tests may not run there. If a reviewer cannot run them, it says so
rather than guessing. If it can, it uses SQLite with a dummy
`DJANGO_SECRET_KEY` and runs only what is cheap; Postgres runs belong to the
main agent, one at a time (parallel runs share a test database).

## Branch worktree (author changes)

Check the PR's head repository first (`isCrossRepository`, `headRepositoryOwner`
and `maintainerCanModify` in `pr_feedback.sh`):

- Same repo: fetch the head branch from `<remote>`.
- Fork owned by the current user: use the remote that points at that fork
  (`git remote -v`); if none exists, stop and ask. Fetch and push there.
- Anyone else's fork: do not fetch-and-push; stop and tell the human, unless
  they explicitly ask you to push there.

```bash
git fetch <head-remote> <headRefName>
git worktree add -b <headRefName> .worktrees/pr-<n>-followup <head-remote>/<headRefName>
```

If a local branch named `<headRefName>` already exists, do not reset it: use
its existing worktree if it has one, otherwise stop and ask the human. Never
use `-B`.

## Cleanup

```bash
git worktree remove .worktrees/pr-<n>-<name>
```

Without `--force`. If git refuses because of changes, tell the human; force
only with their say-so.
