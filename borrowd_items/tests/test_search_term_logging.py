from django.test import RequestFactory, TestCase

from borrowd_groups.views import GroupListView
from borrowd_items.views import ItemListView
from borrowd_users.models import BorrowdUser, SearchTerm, SearchTarget


class SearchTermLoggingTests(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create(
            username="search_user",
            email="search_user@example.com",
        )
        self.factory = RequestFactory()

    def test_item_search_is_logged_without_deduping(self) -> None:
        request = self.factory.get("/items/", {"search": "  Drill  "})
        request.user = self.user

        ItemListView.as_view()(request)

        self.assertEqual(SearchTerm.objects.count(), 1)
        term = SearchTerm.objects.first()
        assert term is not None
        self.assertEqual(term.target, SearchTarget.ITEMS)
        self.assertEqual(term.term_normalized, "drill")
        self.assertEqual(term.term_raw, "Drill")

        # Same term, different casing/whitespace: should create a new row.
        request2 = self.factory.get("/items/", {"search": "drill"})
        request2.user = self.user

        ItemListView.as_view()(request2)

        self.assertEqual(SearchTerm.objects.count(), 2)
        terms = SearchTerm.objects.order_by("created_at")
        self.assertEqual(terms[0].term_raw, "Drill")
        self.assertEqual(terms[1].term_raw, "drill")
        self.assertEqual(terms[0].term_normalized, "drill")
        self.assertEqual(terms[1].term_normalized, "drill")

    def test_group_search_is_logged_without_deduping(self) -> None:
        request = self.factory.get("/groups/", {"search": "  Camping  "})
        request.user = self.user

        GroupListView.as_view()(request)

        self.assertEqual(SearchTerm.objects.count(), 1)
        term = SearchTerm.objects.first()
        assert term is not None
        self.assertEqual(term.target, SearchTarget.GROUPS)
        self.assertEqual(term.term_normalized, "camping")
        self.assertEqual(term.term_raw, "Camping")

        request2 = self.factory.get("/groups/", {"search": "camping"})
        request2.user = self.user
        GroupListView.as_view()(request2)

        self.assertEqual(SearchTerm.objects.count(), 2)
