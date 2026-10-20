# Use of AI at Borrow'd

Borrow'd exists to make a positive difference for the environment and our
communities. AI is in tension with that mission: it carries real environmental
and social costs, and it is also the reason we have come as far as we have. We
hold both truths. We use AI deliberately, watch its impact, and will revisit
this policy as the tools and our understanding change.

We are also a community-driven open source project. Anyone should be able to
read, understand, and contribute to this code, so it must always be legible to
a human. This policy applies to contributors and to the AI agents working for
them; "you" means either, and the human is always accountable. AI is welcome
for code, tests, docs, review, triage, and replying to comments, and the policy
covers all of them, including issues and bug reports.

## Outcomes we expect

1. **You understand what you submit.** You can explain what it does, why it's
   written that way, and how you tested it. "The AI wrote it" is not an answer
   in review.
2. **You understand what you approve.** You have verified a review's
   conclusions yourself before posting them, whoever drafted them.
3. **Other humans can follow the trail.** Reviewers and future maintainers can
   tell what changed, why, and how it fits into the system.
4. **No sensitive data reaches an AI tool.** User data, credentials, secrets,
   and production information stay out.
5. **Nothing enters the repo that doesn't fit our license.** Borrow'd is
   AGPL-3.0, and you must have the right to submit everything you contribute
   under it.

## Leaving a trail

- **Start with a TL;DR.** The PR `Summary` opens with a plain-language TL;DR:
  what changed, why, and how it fits into the system. You stand behind it,
  whoever drafted it.
- **Describe the final state.** PR descriptions and code comments say what the
  code is and why, not how you got there.
- **Keep changes small.** AI makes large changes cheap to write and expensive
  to review. Prefer focused PRs that follow existing conventions.
- **Test beyond unit tests.** Run the app and use the change as a user would.
- **Say when AI played a significant role.** One line in the PR description is
  enough (e.g. "used AI to draft the migration, then rewrote and tested it").
  It helps reviewers know where to look and is never held against you. Commits
  made by an agent keep their `Co-Authored-By` trailer.

Maintainers may close a PR without detailed review if it has no TL;DR, is too
large to review, or its author can't explain it.

## Sensitive data

Never give an AI tool user data, credentials, secrets, or production
information, such as `.env` files, database dumps, or production logs. Local
`db.sqlite3` and `media/` are off-limits too, since they can hold real emails
and photos.

## Licensing

AI can reproduce licensed code verbatim. If you can't vouch for where
something came from, don't submit it.

## For AI agents

Follow this policy. In particular:

- Open the PR `Summary` with the TL;DR. Describe the final state, not your
  session: no logs, abandoned attempts, or step-by-step narration, in the PR
  description or in code comments. Comments follow the evergreen rule in
  [AGENTS.md](../AGENTS.md#comments).
- Keep the `Co-Authored-By` trailer, and note significant AI involvement in the
  PR description.
- Don't read, print, or transmit `.env` files, secrets, `db.sqlite3`, `media/`,
  or production data.
- Don't post reviews, issues, or comments the human hasn't verified. Never say
  a human reviewed or tested something unless they told you so.
- Before the PR is ready, suggest manual checks beyond unit tests (run the app,
  walk the flow as each kind of user, try edge and failure cases) and ask what
  the human observed.
- Make sure the human can explain the change; if they can't, explain it to
  them.
- If you're unsure whether code is licensed compatibly, say so and don't commit
  it.
