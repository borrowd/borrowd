"""
The analytics queries in docs/analytics/ hard-code table and column names and
TransactionStatus integers, so a migration or renumbering would break them
silently. These tests run every query against the test database and check
each status integer against the name written beside it.
"""

import re
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.db import connection, transaction
from django.test import SimpleTestCase, TestCase

from borrowd_items.models import TransactionStatus

ANALYTICS_DIR = Path(settings.BASE_DIR) / "docs" / "analytics"
QUERY_FILES = sorted((ANALYTICS_DIR / "queries").glob("*.sql"))

STATUS_NAME = r"[A-Z][A-Z_]+"
# A line whose trailing comment is only status names, e.g.
# `WHERE status IN (70, 95)  -- RETURNED, OWNERSHIP_TRANSFERRED`.
NAMED_STATUS_COMMENT = re.compile(
    rf"^(?P<code>.*?)--\s*(?P<names>{STATUS_NAME}(?:\s*(?:,|->)\s*{STATUS_NAME})*)\s*$"
)
# `WHEN 10 THEN 'REQUESTED'`
STATUS_LABEL = re.compile(rf"\bWHEN (\d{{2}}) THEN '({STATUS_NAME})'")
# `52 \`GIVEAWAY_OFFERED\`` and `\`GIVEAWAY_OFFERED\` (52)` in the README.
README_STATUSES = (
    re.compile(rf"\b(\d{{2}}) `({STATUS_NAME})`"),
    re.compile(rf"`({STATUS_NAME})` \((\d{{2}})\)"),
)


def status_pairs_in_sql(sql: str) -> list[tuple[int, str]]:
    """Every (integer, name) pair a query documents."""
    pairs: list[tuple[int, str]] = []
    for line in sql.splitlines():
        match = NAMED_STATUS_COMMENT.match(line)
        if match:
            numbers = re.findall(r"\b\d{2}\b", match["code"])
            names = re.findall(STATUS_NAME, match["names"])
            if len(numbers) == len(names):
                pairs.extend(zip(map(int, numbers), names, strict=True))
            else:
                pairs.append((-1, f"unmatched: {line.strip()}"))
        pairs.extend((int(n), name) for n, name in STATUS_LABEL.findall(line))
    return pairs


def status_pairs_in_readme(text: str) -> list[tuple[int, str]]:
    number_first, name_first = README_STATUSES
    return [(int(n), name) for n, name in number_first.findall(text)] + [
        (int(n), name) for name, n in name_first.findall(text)
    ]


class AnalyticsStatusIntegerTests(SimpleTestCase):
    def assert_statuses_match(self, pairs: list[tuple[int, str]]) -> None:
        self.assertTrue(pairs, "found no documented status integers")
        for number, name in pairs:
            with self.subTest(status=name):
                self.assertIn(name, TransactionStatus.names)
                self.assertEqual(TransactionStatus[name], number)

    def test_query_statuses_match_transaction_status(self) -> None:
        for path in QUERY_FILES:
            pairs = status_pairs_in_sql(path.read_text())
            if pairs:
                with self.subTest(query=path.name):
                    self.assert_statuses_match(pairs)

    def test_readme_statuses_match_transaction_status(self) -> None:
        readme = (ANALYTICS_DIR / "README.md").read_text()
        self.assert_statuses_match(status_pairs_in_readme(readme))


@skipUnless(
    connection.vendor == "postgresql", "The analytics queries are Postgres SQL."
)
class AnalyticsQueriesRunTests(TestCase):
    def test_found_the_queries(self) -> None:
        self.assertTrue(QUERY_FILES)

    def test_every_query_runs(self) -> None:
        for path in QUERY_FILES:
            # A savepoint each, so one failing query doesn't abort the rest.
            with (
                self.subTest(query=path.name),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(path.read_text())
                cursor.fetchall()
