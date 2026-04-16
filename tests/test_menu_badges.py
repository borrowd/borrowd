import threading
from django.db import transaction, connection
import unittest
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from borrowd_users.models import MenuBadgeState

User = get_user_model()


class MenuBadgeStateModelTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username="alice", password="pw")
		self.badge = MenuBadgeState.for_user(self.user)

	def test_for_user_creates_and_returns(self):
		badge2 = MenuBadgeState.for_user(self.user)
		self.assertEqual(self.badge, badge2)
		self.assertEqual(badge2.user, self.user)

	def test_increment_inventory_sets_count_and_dot(self):
		self.badge.increment_inventory()
		self.badge.refresh_from_db()
		self.assertEqual(self.badge.inventory_count, 1)
		self.assertTrue(self.badge.hamburger_dot_visible)

	def test_increment_groups_sets_count_and_dot(self):
		self.badge.increment_groups(2)
		self.badge.refresh_from_db()
		self.assertEqual(self.badge.groups_count, 2)
		self.assertTrue(self.badge.hamburger_dot_visible)

	def test_clear_inventory_sets_zero(self):
		self.badge.increment_inventory(3)
		self.badge.clear_inventory()
		self.badge.refresh_from_db()
		self.assertEqual(self.badge.inventory_count, 0)

	def test_clear_groups_sets_zero(self):
		self.badge.increment_groups(4)
		self.badge.clear_groups()
		self.badge.refresh_from_db()
		self.assertEqual(self.badge.groups_count, 0)

	def test_clear_hamburger_dot(self):
		self.badge.increment_inventory()
		self.badge.clear_hamburger_dot()
		self.badge.refresh_from_db()
		self.assertFalse(self.badge.hamburger_dot_visible)

	def test_cascading_delete_removes_badge(self):
		user_id = self.user.id
		self.assertTrue(MenuBadgeState.objects.filter(user_id=user_id).exists())
		self.user.delete()
		self.assertFalse(MenuBadgeState.objects.filter(user_id=user_id).exists())


class MenuBadgeStateConcurrencyTests(TransactionTestCase):
	def setUp(self):
		self.user = User.objects.create_user(username="bob", password="pw")
		self.badge = MenuBadgeState.for_user(self.user)

	def _increment_inventory(self, amount, times):
		for _ in range(times):
			with transaction.atomic():
				badge = MenuBadgeState.for_user(self.user)
				badge.increment_inventory(amount)

	@unittest.skipIf(connection.vendor == "sqlite", "SQLite does not support concurrent writes")
	def test_concurrent_inventory_increments(self):
		threads = []
		num_threads = 5
		increments_per_thread = 10

		for _ in range(num_threads):
			t = threading.Thread(
				target=self._increment_inventory,
				args=(1, increments_per_thread),
			)
			threads.append(t)

		for t in threads:
			t.start()

		for t in threads:
			t.join()

		self.badge.refresh_from_db()
		self.assertEqual(
			self.badge.inventory_count,
			num_threads * increments_per_thread,
		)