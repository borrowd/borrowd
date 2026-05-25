"""
Tests for `resolve_back_url`. Resolution priority: `?next=` first,
then Referer, then the caller's fallback URL.
"""

from django.http import HttpRequest
from django.test import RequestFactory, TestCase
from django.urls import reverse

from borrowd.util import resolve_back_url

# URLs that are OK for the Referer to point at
# i.e. real pages that users might actually be coming from,
# not forms or POST endpoints that would be weird to land back on.
_ITEM_DETAIL_ALLOWED_BACK_URL_NAMES = {
    "item-list",
    "item-detail",
    "profile-inventory",
    "index",
    "profile",
}

_TEST_FALLBACK_URL = "/__test_fallback__/"


class ResolveBackUrlTests(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    def _resolve(self, request: HttpRequest) -> str:
        return resolve_back_url(
            request,
            fallback_url=_TEST_FALLBACK_URL,
            allowed_url_names=_ITEM_DETAIL_ALLOWED_BACK_URL_NAMES,
        )

    # -- 1. `?next=` --------------------------------------------

    def test_next_param_internal_url_is_used(self) -> None:
        """Explicit ?next= pointing at an internal page wins outright."""
        inventory_url = reverse("profile-inventory")
        request = self.factory.get(
            f"/items/1/?next={inventory_url}",
            # Even with a referer pointing somewhere else, the explicit
            # `?next=` override should take priority.
            HTTP_REFERER="http://testserver/items/",
        )

        self.assertEqual(self._resolve(request), inventory_url)

    def test_next_param_external_url_is_rejected(self) -> None:
        """
        `?next=` pointing at an external host falls through to the Referer.

        Our same-origin check rejects URLs with a non-matching netloc.
        without it, a crafted link like /items/1/?next=https://evil.example/
        could send the user off-site when they click the back button.
        """
        request = self.factory.get(
            "/items/1/?next=https://evil.example/phish",
            HTTP_REFERER="http://testserver/items/",
        )

        # External ?next= rejected, so we land on the referer (item-list).
        self.assertEqual(self._resolve(request), "/items/")

    def test_next_param_javascript_scheme_is_rejected(self) -> None:
        """
        `?next=javascript:...` is rejected -- only http(s) and relative
        URLs are allowed. This is to prevent XSS via the back link.
        """
        request = self.factory.get(
            "/items/1/?next=javascript:alert(1)",
            HTTP_REFERER="http://testserver/items/",
        )

        # Dangerous scheme rejected, fall back to referer.
        self.assertEqual(self._resolve(request), "/items/")

    # -- 2. Referer fallback ---------------------------------------------

    def test_referer_preserves_query_string(self) -> None:
        """
        Query string on the Referer is kept so the user lands back on
        a filtered/sorted list with their filters intact, not a reset list.
        """
        request = self.factory.get(
            "/items/1/",
            HTTP_REFERER="http://testserver/items/?search=drill",
        )

        self.assertEqual(self._resolve(request), "/items/?search=drill")

    def test_referer_external_origin_is_ignored(self) -> None:
        """A Referer from an external site is not trusted."""
        request = self.factory.get(
            "/items/1/",
            HTTP_REFERER="https://evil.example/items/",
        )

        # External Referer ignored, fall through to default.
        self.assertEqual(self._resolve(request), _TEST_FALLBACK_URL)

    def test_referer_not_on_allowlist_is_ignored(self) -> None:
        """
        Pages outside the allowlist (form pages, POST endpoints, anything
        we haven't explicitly OK'd) are ignored. We fall through to fallback URL
        """
        request = self.factory.get(
            "/items/1/",
            HTTP_REFERER="http://testserver/items/create/",
        )

        self.assertEqual(self._resolve(request), _TEST_FALLBACK_URL)

    def test_referer_inventory_is_honored(self) -> None:
        """
        profile-inventory is on the allowlist, so a Referer from
        inventory is honored.
        """
        inventory_url = reverse("profile-inventory")
        request = self.factory.get(
            "/items/1/",
            HTTP_REFERER=f"http://testserver{inventory_url}",
        )

        self.assertEqual(self._resolve(request), inventory_url)

    def test_referer_on_same_page_is_ignored(self) -> None:
        """
        Don't link the back button to the same page the user is already
        on -- that makes the button a no-op.
        """
        request = self.factory.get(
            "/items/1/",
            HTTP_REFERER="http://testserver/items/1/",
        )

        self.assertEqual(self._resolve(request), _TEST_FALLBACK_URL)

    def test_referer_on_different_detail_page_is_honored(self) -> None:
        """
        A Referer pointing at a different item-detail page is fine --
        users can navigate detail -> detail (e.g. via direct url) and
        the back button should return them to the previous item.
        """
        request = self.factory.get(
            "/items/2/",
            HTTP_REFERER="http://testserver/items/1/",
        )

        self.assertEqual(self._resolve(request), "/items/1/")

    def test_referer_unresolvable_path_is_ignored(self) -> None:
        """
        Path that doesn't map to any of our Django routes (static asset,
        unknown URL, etc.) -- skip and fall back.
        """
        request = self.factory.get(
            "/items/1/",
            HTTP_REFERER="http://testserver/some/path/that/does/not/exist/",
        )

        self.assertEqual(self._resolve(request), _TEST_FALLBACK_URL)

    # -- 3. Fallback -----------------------------------------------------

    def test_no_next_no_referer_falls_back_to_fallback_url(self) -> None:
        """Direct navigation / bookmarks: no signal -> fallback_url."""
        request = self.factory.get("/items/1/")

        self.assertEqual(self._resolve(request), _TEST_FALLBACK_URL)
