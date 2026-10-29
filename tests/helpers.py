from html.parser import HTMLParser
from typing import Protocol

from borrowd_items.models import Item
from borrowd_messaging.models import ChatThread


class _ResponseWithContent(Protocol):
    content: bytes


class _LinkByTextParser(HTMLParser):
    def __init__(self, link_text: str) -> None:
        super().__init__()
        self._link_text = link_text
        self._in_anchor = False
        self._current_href: str | None = None
        self._current_text = ""
        self.href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._in_anchor = True
            self._current_href = dict(attrs).get("href")
            self._current_text = ""

    def handle_data(self, data: str) -> None:
        if self._in_anchor:
            self._current_text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_anchor:
            if self._current_text.strip() == self._link_text:
                self.href = self._current_href
            self._in_anchor = False


def link_href_by_text(response: _ResponseWithContent, link_text: str) -> str:
    """
    Return the href of the <a> element whose rendered text is exactly `link_text`.

    Unlike `assertContains(response, f'href="{url}"')`, this ties the
    assertion to the specific link named `link_text` rather than to any
    element in the response that happens to share its destination URL.
    """
    parser = _LinkByTextParser(link_text)
    parser.feed(response.content.decode())
    if parser.href is None:
        raise AssertionError(f"Response does not contain a {link_text!r} link.")
    return parser.href


def hard_delete_threads_and_transactions(item: Item) -> None:
    """
    Destroy an item's chats and transactions in test teardown.

    Since we have messages and threads set to PROTECT, we have to delete from
    the bottom (messages) up.
    """
    # no-op when no chats (e.g. MESSAGING_ENABLED == false)
    for thread in ChatThread.objects.filter(item=item):
        thread.messages.all().delete()
        thread.delete()
    # always runs
    for tx in item.transactions.all():
        tx.delete()
