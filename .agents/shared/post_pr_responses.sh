#!/usr/bin/env bash
# Post follow-up responses to a pull request: a review, thread replies, a
# top-level comment, and thread resolutions. Schema and rules: see
# .agents/shared/pr-comments.md.
#
# Usage: post_pr_responses.sh <pr-number> <actions.json> [--post --expect-head <sha>]
#
# Without --post this is a dry run: it validates the file (including that every
# inline comment sits on a diff line and every thread belongs to the PR) and
# prints what would be submitted, plus the head commit to pass as --expect-head.
# With --post it refuses to run if the PR head is not the expected commit.
#
# Posting order: review, replies, top-level comment, resolutions. If a step
# fails, the run stops and lists what had already been posted; remove those
# entries from the file before retrying.
#
# Repo: taken from GH_REPO if set, else the current directory's default repo.
set -euo pipefail

usage() {
  echo "usage: $0 <pr-number> <actions.json> [--post --expect-head <sha>]" >&2
  exit 2
}

[[ $# -ge 2 ]] || usage
pr="$1"
file="$2"
shift 2

post=0
expect_head=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --post) post=1 ;;
    --expect-head) expect_head="${2:-}"; shift ;;
    *) usage ;;
  esac
  shift
done

if [[ ! "$pr" =~ ^[0-9]+$ ]]; then
  echo "error: PR number must be numeric" >&2
  exit 2
fi
if [[ ! -f "$file" ]]; then
  echo "error: $file not found" >&2
  exit 2
fi
if ((post)) && [[ -z "$expect_head" ]]; then
  echo "error: --post requires --expect-head <sha> (shown by the dry run)" >&2
  exit 2
fi

jq -e '
  def nonempty_string: type == "string" and length > 0;
  ((.replies // []) | all((.thread_id | nonempty_string) and (.body | nonempty_string))) and
  ((.resolve // []) | all(nonempty_string)) and
  ((.pr_comment // "x") | nonempty_string) and
  (if .review == null then true else
    (.review.event | IN("APPROVE", "COMMENT", "REQUEST_CHANGES")) and
    (.review.body | nonempty_string) and
    ((.review.comments // []) | all(
      (.path | type == "string") and (.line | type == "number") and (.body | nonempty_string)
    ))
  end)
' "$file" >/dev/null || {
  echo "error: $file is not a valid actions file (see .agents/shared/pr-comments.md)" >&2
  exit 2
}

repo="${GH_REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
meta="$(gh pr view "$pr" -R "$repo" --json state,headRefOid,author)"
state="$(jq -r .state <<<"$meta")"
head="$(jq -r .headRefOid <<<"$meta")"
author="$(jq -r .author.login <<<"$meta")"

if [[ "$state" != "OPEN" ]]; then
  echo "error: PR #$pr is $state, not OPEN" >&2
  exit 1
fi
if [[ -n "$expect_head" && "$expect_head" != "$head" ]]; then
  echo "error: PR head is $head but $expect_head was expected; re-check the changes and redraft" >&2
  exit 1
fi

errors=()

# GitHub rejects approving or requesting changes on one's own PR. A token that
# cannot report its user (for example an app token) skips this check.
me="$(gh api user -q .login 2>/dev/null || true)"
event="$(jq -r '.review.event // empty' "$file")"
if [[ -n "$me" && "$me" == "$author" && -n "$event" && "$event" != "COMMENT" ]]; then
  errors+=("you are the PR author; GitHub rejects $event on your own PR. Use COMMENT.")
fi

# Inline comments must sit on a line that appears in the PR diff (new side).
if [[ "$(jq '(.review.comments // []) | length' "$file")" -gt 0 ]]; then
  valid="$(gh api --paginate "repos/$repo/pulls/$pr/files?per_page=100" | jq -s '
    def right_lines:
      (.patch // "") | split("\n")
      | reduce .[] as $l ({n: 0, out: []};
          if $l == "" or ($l | startswith("-")) or ($l | startswith("\\")) then .
          elif ($l | startswith("@@")) then
            .n = (($l | capture("\\+(?<s>[0-9]+)").s | tonumber) - 1)
          else .n += 1 | .out += [.n] end)
      | .out;
    add | map({key: .filename, value: right_lines}) | from_entries')"
  while IFS= read -r bad; do
    errors+=("inline comment is not on a line in the PR diff: $bad")
  done < <(jq -r --argjson valid "$valid" '
    (.review.comments // [])[] | . as $c
    | select(($valid[$c.path] // []) | index($c.line) | not)
    | "\($c.path):\($c.line)"' "$file")
fi

# Threads must belong to this PR.
thread_query='query($id: ID!) { node(id: $id) {
  ... on PullRequestReviewThread { isResolved pullRequest { number repository { nameWithOwner } } }
} }'
while IFS= read -r id; do
  [[ -n "$id" ]] || continue
  info="$(gh api graphql -f query="$thread_query" -f id="$id" 2>/dev/null || true)"
  if ! jq -e --argjson pr "$pr" --arg repo "$repo" '
      .data.node.pullRequest
      | . != null and .number == $pr
        and (.repository.nameWithOwner | ascii_downcase) == ($repo | ascii_downcase)
    ' <<<"$info" >/dev/null 2>&1; then
    errors+=("thread $id is not a review thread on PR #$pr")
  elif [[ "$(jq -r .data.node.isResolved <<<"$info")" == "true" ]]; then
    echo "note: thread $id is already resolved"
  fi
done < <(jq -r '((.replies // [])[].thread_id), ((.resolve // [])[])' "$file" | sort -u)

if ((${#errors[@]})); then
  printf 'error: %s\n' "${errors[@]}" >&2
  exit 1
fi

echo "PR #$pr in $repo at head $head"
jq -r '
  (if .review then
     "REVIEW (\(.review.event)), \((.review.comments // []) | length) inline comments:\n\(.review.body)\n",
     ((.review.comments // [])[] | "  --- \(.path):\(.line)\n  \(.body)\n")
   else empty end),
  ((.replies // [])[] | "REPLY to thread \(.thread_id):\n\(.body)\n"),
  (if .pr_comment then "PR COMMENT:\n\(.pr_comment)\n" else empty end),
  ((.resolve // [])[] | "RESOLVE thread \(.)")
' "$file"

if ((!post)); then
  echo "(dry run; to submit: $0 $pr $file --post --expect-head $head)"
  exit 0
fi

posted=()
report_progress() {
  local rc=$?
  if ((rc != 0 && ${#posted[@]} > 0)); then
    echo "Already posted before the failure (remove these from the file before retrying):" >&2
    printf '  %s\n' "${posted[@]}" >&2
  fi
}
trap report_progress EXIT

if jq -e '.review' "$file" >/dev/null; then
  payload="$(jq --arg sha "$head" '
    .review | {commit_id: $sha, event, body,
               comments: [(.comments // [])[] | {path, line, side: "RIGHT", body}]}
  ' "$file")"
  # GitHub allows one pending review per user per PR; a leftover pending
  # review makes this call fail.
  url="$(gh api -X POST "repos/$repo/pulls/$pr/reviews" --input - -q .html_url <<<"$payload")"
  posted+=("review: $url")
  echo "posted review: $url"
fi

reply_mutation='mutation($id: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $id, body: $body}) {
    comment { url }
  }
}'
while IFS= read -r item; do
  id="$(jq -r .thread_id <<<"$item")"
  body="$(jq -r .body <<<"$item")"
  url="$(gh api graphql -f query="$reply_mutation" -f id="$id" -f body="$body" \
    -q .data.addPullRequestReviewThreadReply.comment.url)"
  posted+=("reply to $id: $url")
  echo "posted reply: $url"
done < <(jq -c '(.replies // [])[]' "$file")

if jq -e '.pr_comment' "$file" >/dev/null; then
  body="$(jq -r .pr_comment "$file")"
  url="$(gh pr comment "$pr" -R "$repo" --body "$body")"
  posted+=("comment: $url")
  echo "posted comment: $url"
fi

resolve_mutation='mutation($id: ID!) {
  resolveReviewThread(input: {threadId: $id}) { thread { isResolved } }
}'
while IFS= read -r id; do
  gh api graphql -f query="$resolve_mutation" -f id="$id" >/dev/null
  posted+=("resolved $id")
  echo "resolved thread $id"
done < <(jq -r '(.resolve // [])[]' "$file")
