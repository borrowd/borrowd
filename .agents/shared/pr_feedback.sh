#!/usr/bin/env bash
# Collect what is needed to follow up on a pull request as JSON on stdout: the
# current user, PR metadata (including CI and review state), reviews, review
# threads with resolution state, top-level comments, and commits.
#
# Usage: pr_feedback.sh <pr-number> [--unresolved]
#
#   --unresolved   leave out resolved threads (their count is still reported)
#
# Repo: taken from GH_REPO if set, else the current directory's default repo.
set -euo pipefail

usage() {
  echo "usage: $0 <pr-number> [--unresolved]" >&2
  exit 2
}

[[ $# -ge 1 && $# -le 2 && "$1" =~ ^[0-9]+$ ]] || usage
pr="$1"
unresolved_only=false
if [[ $# -eq 2 ]]; then
  [[ "$2" == "--unresolved" ]] || usage
  unresolved_only=true
fi

repo="${GH_REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
owner="${repo%/*}"
name="${repo#*/}"
# A token that cannot report its user (for example an app token) leaves this
# empty; the role is then reported as "unknown".
me="$(gh api user -q .login 2>/dev/null || true)"

read -r -d '' query <<'GRAPHQL' || true
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number title url state isDraft body reviewDecision mergeable
      author { login }
      baseRefName baseRefOid headRefName headRefOid
      isCrossRepository maintainerCanModify
      headRepository { nameWithOwner url owner { login } }
      reviews(last: 100) {
        pageInfo { hasPreviousPage }
        nodes {
          id state submittedAt body url
          author { login }
          commit { oid }
        }
      }
      reviewThreads(first: 100) {
        pageInfo { hasNextPage }
        nodes {
          id isResolved isOutdated path line originalLine
          comments(first: 50) {
            pageInfo { hasNextPage }
            nodes {
              id url body createdAt
              author { login __typename }
              originalCommit { oid }
              pullRequestReview { id }
            }
          }
        }
      }
      comments(last: 100) {
        pageInfo { hasPreviousPage }
        nodes { id url body createdAt author { login } }
      }
      commits(last: 100) {
        totalCount
        nodes { commit { oid committedDate messageHeadline } }
      }
      latest: commits(last: 1) {
        nodes { commit { statusCheckRollup { state } } }
      }
    }
  }
}
GRAPHQL

data="$(gh api graphql -f query="$query" -f owner="$owner" -f name="$name" \
  -F number="$pr")"

jq --arg me "$me" --argjson unresolved_only "$unresolved_only" '
  .data.repository.pullRequest as $p
  | ([$p.reviewThreads.nodes[]
      | select(.comments.nodes[0].author.login == $me)
      | .comments.nodes[0].pullRequestReview.id]) as $my_thread_reviews
  | [$p.reviews.nodes[]
     | select(.author.login == $me
              and (.state | IN("APPROVED", "CHANGES_REQUESTED", "COMMENTED")))
     | select(.state != "COMMENTED"
              or ((.body | length) > 0)
              or (.id | IN($my_thread_reviews[])))
    ] | sort_by(.submittedAt) | last as $baseline
  | {
      me: $me,
      is_author: ($me != "" and $p.author.login == $me),
      role_hint: (if $me == "" then "unknown"
                  elif $p.author.login == $me then "author"
                  else "reviewer" end),
      has_reviewed: any($p.reviews.nodes[];
                        .author.login == $me and .state != "PENDING"),
      baseline_review: ($baseline | if . == null then null
                        else {id, state, submittedAt, commit: .commit.oid} end),
      pr: ($p | {number, title, url, state, isDraft, body, author: .author.login,
                 reviewDecision, mergeable, baseRefName, baseRefOid, headRefName,
                 headRefOid, isCrossRepository, maintainerCanModify,
                 headRepository: .headRepository.nameWithOwner,
                 headRepositoryOwner: .headRepository.owner.login,
                 headRepositoryUrl: .headRepository.url,
                 checks: ($p.latest.nodes[0].commit.statusCheckRollup.state)}),
      reviews: [$p.reviews.nodes[]
                | {id, state, submittedAt, body, url,
                   author: .author.login, commit: .commit.oid}],
      threads: [$p.reviewThreads.nodes[]
                | select(($unresolved_only | not) or (.isResolved | not))
                | {id, isResolved, isOutdated, path, line, originalLine,
                   comments: [.comments.nodes[]
                              | {id, url, body, createdAt,
                                 author: .author.login,
                                 author_is_bot: (.author.__typename == "Bot"),
                                 originalCommit: .originalCommit.oid}]}],
      resolved_thread_count: ([$p.reviewThreads.nodes[] | select(.isResolved)] | length),
      comments: [$p.comments.nodes[]
                 | {id, url, body, createdAt, author: .author.login}],
      commits: [$p.commits.nodes[].commit
                | {oid, committedDate, messageHeadline}],
      warnings: ([
        (if $p.reviews.pageInfo.hasPreviousPage then "older reviews omitted (showing the latest 100)" else empty end),
        (if $p.reviewThreads.pageInfo.hasNextPage then "review threads truncated at 100" else empty end),
        (if $p.comments.pageInfo.hasPreviousPage then "older comments omitted (showing the latest 100)" else empty end),
        (if any($p.reviewThreads.nodes[]; .comments.pageInfo.hasNextPage) then "a thread has more than 50 comments" else empty end),
        (if $p.commits.totalCount > 100 then "commit list shows the latest 100 of \($p.commits.totalCount)" else empty end)
      ])
    }
' <<<"$data"
