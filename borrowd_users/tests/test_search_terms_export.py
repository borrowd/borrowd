from django.test import Client, TestCase

from borrowd_users.models import BorrowdUser, SearchTarget, SearchTerm


class SearchTermsExportViewTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.admin = BorrowdUser.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="pw12345",
            is_staff=True,
        )
        self.user = BorrowdUser.objects.create_user(
            username="member",
            email="member@example.com",
            password="pw12345",
        )

        SearchTerm.record_search(self.user, SearchTarget.ITEMS, "keyboard")
        SearchTerm.record_search(self.user, SearchTarget.GROUPS, "camping")

    def test_non_staff_user_gets_forbidden(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get("/profile/search-terms/export/")
        self.assertEqual(response.status_code, 403)

    def test_staff_user_gets_json_results(self) -> None:
        self.client.force_login(self.admin)
        response = self.client.get("/profile/search-terms/export/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertIn("results", payload)
        self.assertTrue(all("user_id" in row for row in payload["results"]))
        self.assertTrue(all("created_at" in row for row in payload["results"]))
        self.assertTrue(all("last_searched_at" not in row for row in payload["results"]))

    def test_filters_by_target_and_user_id(self) -> None:
        self.client.force_login(self.admin)
        response = self.client.get(
            "/profile/search-terms/export/",
            {"target": "items", "user_id": self.user.pk},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["target"], "items")
        self.assertEqual(payload["results"][0]["user_id"], self.user.pk)
