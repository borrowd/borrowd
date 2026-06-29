"""
Tests for account (soft) deletion: the `soft_delete_account` service and the
`delete_account_view` endpoint.
"""

import shutil
import tempfile
from io import BytesIO

from allauth.account.models import EmailAddress
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from notifications.models import Notification
from PIL import Image

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import (
    AvailabilitySubscription,
    AvailabilitySubscriptionStatus,
    Item,
    ItemPhoto,
    ItemStatus,
    Transaction,
    TransactionStatus,
)
from borrowd_notifications.models import NotificationType
from borrowd_users.exceptions import AccountDeletionBlocked
from borrowd_users.models import BorrowdUser
from borrowd_users.services import soft_delete_account

_TEST_MEDIA_ROOT = tempfile.mkdtemp()


def tearDownModule() -> None:
    shutil.rmtree(_TEST_MEDIA_ROOT, ignore_errors=True)


def _image_upload(name: str = "photo.jpg") -> SimpleUploadedFile:
    """A tiny valid in-memory JPEG suitable for ProcessedImageField."""
    buffer = BytesIO()
    Image.new("RGB", (10, 10), color="red").save(buffer, format="JPEG")
    buffer.seek(0)
    return SimpleUploadedFile(name, buffer.read(), content_type="image/jpeg")


def _make_user(username: str) -> BorrowdUser:
    return BorrowdUser.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="password",
        first_name="Real",
        last_name="Name",
    )


def _make_item(owner: BorrowdUser, name: str = "Drill") -> Item:
    return Item.objects.create(
        name=name,
        description="A useful thing",
        owner=owner,
        created_by=owner,
        updated_by=owner,
        trust_level_required=TrustLevel.STANDARD,
    )


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT)
class AccountDeletionServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = _make_user("alice")
        self.other = _make_user("bob")

    def test_anonymizes_and_deactivates_user(self) -> None:
        pk = self.user.pk
        soft_delete_account(self.user, deleted_by=self.user)

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Deleted")
        self.assertEqual(self.user.last_name, "User")
        self.assertEqual(self.user.username, f"deleted_{pk}")
        self.assertEqual(self.user.email, f"deleted_{pk}@borrowd.org")
        self.assertFalse(self.user.is_active)
        self.assertIsNotNone(self.user.deleted_at)
        self.assertEqual(self.user.deleted_by, self.user)
        self.assertFalse(self.user.has_usable_password())

    def test_removes_allauth_email_addresses(self) -> None:
        EmailAddress.objects.create(
            user=self.user, email=self.user.email, primary=True, verified=True
        )
        soft_delete_account(self.user, deleted_by=self.user)
        self.assertFalse(EmailAddress.objects.filter(user=self.user).exists())

    def test_soft_deletes_owned_items_and_hides_them(self) -> None:
        _make_item(self.user, "Hammer")
        _make_item(self.user, "Saw")

        soft_delete_account(self.user, deleted_by=self.user)

        # Hidden from the active-item manager...
        self.assertEqual(Item.objects.filter(owner=self.user).count(), 0)
        # ...but the rows are kept (soft delete) with audit fields set.
        kept = Item.all_objects.filter(owner=self.user)
        self.assertEqual(kept.count(), 2)
        for item in kept:
            self.assertIsNotNone(item.deleted_at)
            self.assertEqual(item.deleted_by, self.user)

    def test_destroys_item_photos(self) -> None:
        item = _make_item(self.user)
        ItemPhoto.objects.create(
            item=item,
            image=_image_upload(),
            created_by=self.user,
            updated_by=self.user,
        )
        self.assertEqual(ItemPhoto.objects.filter(item=item).count(), 1)

        soft_delete_account(self.user, deleted_by=self.user)

        # Photos are permanently destroyed (rows gone), not soft-deleted.
        self.assertEqual(ItemPhoto.objects.filter(item=item).count(), 0)

    def test_destroys_profile_photo_and_clears_bio(self) -> None:
        profile = self.user.profile
        profile.bio = "Hello there"
        profile.image = _image_upload("avatar.jpg")
        profile.save()

        soft_delete_account(self.user, deleted_by=self.user)

        profile.refresh_from_db()
        self.assertFalse(bool(profile.image))
        self.assertEqual(profile.bio, "")

    def test_cancels_subscriptions(self) -> None:
        others_item = _make_item(self.other)
        AvailabilitySubscription.objects.create(
            user=self.user,
            item=others_item,
            status=AvailabilitySubscriptionStatus.ACTIVE,
        )
        soft_delete_account(self.user, deleted_by=self.user)
        self.assertFalse(
            AvailabilitySubscription.objects.filter(
                user=self.user, status=AvailabilitySubscriptionStatus.ACTIVE
            ).exists()
        )


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT)
class AccountDeletionTransactionTests(TestCase):
    def setUp(self) -> None:
        self.leaver = _make_user("leaver")
        self.counterparty = _make_user("counter")

    def _txn(
        self,
        *,
        item: Item,
        party1: BorrowdUser,
        party2: BorrowdUser,
        status: int,
    ) -> Transaction:
        return Transaction.objects.create(
            item=item,
            party1=party1,
            party2=party2,
            status=status,
            created_by=party2,
            updated_by=party2,
        )

    def test_cancels_open_request_and_frees_counterpartys_item(self) -> None:
        # Leaver requested the counterparty's item (leaver is borrower/party2).
        item = _make_item(self.counterparty)
        item.status = ItemStatus.REQUESTED
        item.save()
        txn = self._txn(
            item=item,
            party1=self.counterparty,
            party2=self.leaver,
            status=TransactionStatus.REQUESTED,
        )

        soft_delete_account(self.leaver, deleted_by=self.leaver)

        txn.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(txn.status, TransactionStatus.CANCELLED)
        self.assertEqual(item.status, ItemStatus.AVAILABLE)

    def test_cancels_open_request_on_own_item(self) -> None:
        # Someone requested the leaver's item (leaver is owner/party1).
        item = _make_item(self.leaver)
        item.status = ItemStatus.REQUESTED
        item.save()
        txn = self._txn(
            item=item,
            party1=self.leaver,
            party2=self.counterparty,
            status=TransactionStatus.REQUESTED,
        )

        soft_delete_account(self.leaver, deleted_by=self.leaver)

        txn.refresh_from_db()
        self.assertEqual(txn.status, TransactionStatus.CANCELLED)

    def test_owner_leaving_mid_loan_leaves_loan_open_and_notifies_borrower(
        self,
    ) -> None:
        # Leaver is lending an item the borrower currently holds.
        item = _make_item(self.leaver)
        item.status = ItemStatus.BORROWED
        item.save()
        txn = self._txn(
            item=item,
            party1=self.leaver,
            party2=self.counterparty,
            status=TransactionStatus.COLLECTED,
        )
        Notification.objects.all().delete()

        soft_delete_account(self.leaver, deleted_by=self.leaver)

        txn.refresh_from_db()
        # Left open: the borrower closes it out themselves via the
        # counterparty-gone action, not the normal dual-confirm.
        self.assertEqual(txn.status, TransactionStatus.COLLECTED)
        # And they're told what happened so they can arrange the return.
        self.assertEqual(
            Notification.objects.filter(
                verb=NotificationType.LOAN_ENDED_OWNER_LEFT.value,
                recipient=self.counterparty,
            ).count(),
            1,
        )

    def test_preserves_completed_transaction(self) -> None:
        item = _make_item(self.leaver)
        txn = self._txn(
            item=item,
            party1=self.leaver,
            party2=self.counterparty,
            status=TransactionStatus.RETURNED,
        )

        soft_delete_account(self.leaver, deleted_by=self.leaver)

        txn.refresh_from_db()
        self.assertEqual(txn.status, TransactionStatus.RETURNED)

    def test_notifies_owner_when_borrower_leaves(self) -> None:
        # Leaver requested the owner's item (leaver is borrower/party2), so the
        # owner is told their item is free again.
        item = _make_item(self.counterparty)
        self._txn(
            item=item,
            party1=self.counterparty,
            party2=self.leaver,
            status=TransactionStatus.REQUESTED,
        )
        Notification.objects.all().delete()

        soft_delete_account(self.leaver, deleted_by=self.leaver)

        notifications = Notification.objects.filter(
            verb=NotificationType.REQUEST_CANCELLED_BORROWER_LEFT.value,
            recipient=self.counterparty,
        )
        self.assertEqual(notifications.count(), 1)

    def test_notifies_borrower_when_owner_leaves(self) -> None:
        # Someone requested the leaver's item (leaver is owner/party1), so the
        # borrower is told the item is gone.
        item = _make_item(self.leaver)
        self._txn(
            item=item,
            party1=self.leaver,
            party2=self.counterparty,
            status=TransactionStatus.REQUESTED,
        )
        Notification.objects.all().delete()

        soft_delete_account(self.leaver, deleted_by=self.leaver)

        notifications = Notification.objects.filter(
            verb=NotificationType.REQUEST_CANCELLED_OWNER_LEFT.value,
            recipient=self.counterparty,
        )
        self.assertEqual(notifications.count(), 1)


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT)
class AccountDeletionBorrowGuardTests(TestCase):
    def setUp(self) -> None:
        self.borrower = _make_user("borrower")
        self.lender = _make_user("lender")

    def test_blocks_when_actively_borrowing(self) -> None:
        item = _make_item(self.lender)
        item.status = ItemStatus.BORROWED
        item.save()
        Transaction.objects.create(
            item=item,
            party1=self.lender,
            party2=self.borrower,
            status=TransactionStatus.COLLECTED,
            created_by=self.borrower,
            updated_by=self.borrower,
        )

        with self.assertRaises(AccountDeletionBlocked):
            soft_delete_account(self.borrower, deleted_by=self.borrower)

        # Nothing should have changed: the guard runs before any mutation.
        self.borrower.refresh_from_db()
        self.assertTrue(self.borrower.is_active)
        self.assertEqual(self.borrower.username, "borrower")

    def test_blocks_when_return_asserted_but_unconfirmed(self) -> None:
        # Borrower asserted the return but the lender hasn't confirmed it yet.
        # An asserted-but-unconfirmed return isn't proof the item came back, so
        # deletion stays blocked.
        item = _make_item(self.lender)
        item.status = ItemStatus.BORROWED
        item.save()
        Transaction.objects.create(
            item=item,
            party1=self.lender,
            party2=self.borrower,
            status=TransactionStatus.RETURN_ASSERTED,
            created_by=self.borrower,
            updated_by=self.borrower,
        )

        with self.assertRaises(AccountDeletionBlocked):
            soft_delete_account(self.borrower, deleted_by=self.borrower)

        self.borrower.refresh_from_db()
        self.assertTrue(self.borrower.is_active)

    def test_accepted_borrow_is_cancelled_not_blocked(self) -> None:
        # Borrower reserved an item but never collected it: nothing has changed
        # hands, so deletion proceeds and the reservation is just cancelled.
        item = _make_item(self.lender)
        item.status = ItemStatus.RESERVED
        item.save()
        txn = Transaction.objects.create(
            item=item,
            party1=self.lender,
            party2=self.borrower,
            status=TransactionStatus.ACCEPTED,
            created_by=self.borrower,
            updated_by=self.borrower,
        )

        soft_delete_account(self.borrower, deleted_by=self.borrower)

        self.borrower.refresh_from_db()
        self.assertFalse(self.borrower.is_active)
        txn.refresh_from_db()
        self.assertEqual(txn.status, TransactionStatus.CANCELLED)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.AVAILABLE)


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT)
class AccountDeletionGroupTests(TestCase):
    def setUp(self) -> None:
        self.user = _make_user("groupuser")
        self.other = _make_user("groupother")

    def _group(self, creator: BorrowdUser, name: str) -> BorrowdGroup:
        return BorrowdGroup.objects.create_group(
            name=name,
            created_by=creator,
            updated_by=creator,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )

    def test_membership_removed_but_group_kept_when_not_sole_moderator(self) -> None:
        # `other` owns the group; `user` is a plain member.
        group = self._group(self.other, "Bob's Group")
        group.add_user(self.user, trust_level=TrustLevel.STANDARD)

        soft_delete_account(self.user, deleted_by=self.user)

        self.assertFalse(
            Membership.objects.filter(user=self.user, group=group).exists()
        )
        self.assertTrue(BorrowdGroup.objects.filter(pk=group.pk).exists())

    def test_sole_moderator_deletion_triggers_handoff(self) -> None:
        # `user` created (and solely moderates) a group that `other` belongs to.
        group = self._group(self.user, "Alice's Group")
        group.add_user(self.other, trust_level=TrustLevel.STANDARD)
        Notification.objects.all().delete()

        soft_delete_account(self.user, deleted_by=self.user)

        # Group survives (other is still an active member) and the remaining
        # member is told it needs a moderator.
        self.assertTrue(BorrowdGroup.objects.filter(pk=group.pk).exists())
        self.assertTrue(
            Notification.objects.filter(
                verb=NotificationType.GROUP_NEEDS_MODERATOR.value,
                recipient=self.other,
            ).exists()
        )

    def test_empty_group_is_destroyed(self) -> None:
        group = self._group(self.user, "Solo Group")
        # user is the only member.

        soft_delete_account(self.user, deleted_by=self.user)

        self.assertFalse(BorrowdGroup.objects.filter(pk=group.pk).exists())


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT)
class DeleteAccountViewTests(TestCase):
    def setUp(self) -> None:
        self.user = _make_user("viewuser")
        self.url = reverse("account-delete")

    def test_url_takes_no_pk(self) -> None:
        # Structural IDOR prevention: the route is pk-less, so it can only ever act on the logged-in user.
        self.assertTrue(self.url.endswith("/delete/"))
        with self.assertRaises(NoReverseMatch):
            reverse("account-delete", args=[self.user.pk])

    def test_get_not_allowed(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_anonymous_redirected_to_login(self) -> None:
        response = self.client.post(self.url, {"confirm_username": "viewuser"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_username_mismatch_does_not_delete(self) -> None:
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"confirm_username": "wrong"})

        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.username, "viewuser")

    def test_happy_path_deletes_and_redirects(self) -> None:
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"confirm_username": "viewuser"})

        self.assertRedirects(
            response, reverse("profile-deleted"), fetch_redirect_response=False
        )
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_session_invalidated_after_delete(self) -> None:
        self.client.force_login(self.user)
        self.client.post(self.url, {"confirm_username": "viewuser"})

        # Stale session cookie should resolve to anonymous -> login redirect,
        # not a 500.
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_cannot_delete_another_user(self) -> None:
        victim = _make_user("victim")
        self.client.force_login(self.user)

        # The form only carries a username to confirm; there's no way to target
        # another account. Confirming with the victim's username just fails the
        # match against the logged-in user.
        response = self.client.post(self.url, {"confirm_username": "victim"})

        self.assertRedirects(response, reverse("profile"))
        victim.refresh_from_db()
        self.user.refresh_from_db()
        self.assertTrue(victim.is_active)
        self.assertTrue(self.user.is_active)


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT)
class PublicProfileAfterDeletionTests(TestCase):
    def setUp(self) -> None:
        self.viewer = _make_user("viewer")
        self.subject = _make_user("subject")
        # Put them in a shared group so the viewer is normally allowed to see
        # the subject's public profile.
        group = BorrowdGroup.objects.create_group(
            name="Shared",
            created_by=self.viewer,
            updated_by=self.viewer,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )
        group.add_user(self.subject, trust_level=TrustLevel.STANDARD)

    def test_public_profile_visible_before_deletion(self) -> None:
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("public-profile", args=[self.subject.pk]))
        self.assertEqual(response.status_code, 200)

    def test_public_profile_404_after_deletion(self) -> None:
        soft_delete_account(self.subject, deleted_by=self.subject)

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("public-profile", args=[self.subject.pk]))
        self.assertEqual(response.status_code, 404)


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT)
class ProfileViewDeleteFlagsTests(TestCase):
    """The modal-driving flags on the profile page."""

    def setUp(self) -> None:
        self.user = _make_user("flaguser")
        self.client.force_login(self.user)

    def test_clean_account_flags(self) -> None:
        response = self.client.get(reverse("profile"))
        self.assertFalse(response.context["is_borrowing"])
        self.assertFalse(response.context["is_lending"])
        self.assertFalse(response.context["has_items"])

    def test_owning_idle_items_sets_has_items_but_not_is_lending(self) -> None:
        # Owns an item that isn't out on loan: warn it'll be removed, but don't
        # claim they're "still lending".
        _make_item(self.user)
        response = self.client.get(reverse("profile"))
        self.assertFalse(response.context["is_borrowing"])
        self.assertFalse(response.context["is_lending"])
        self.assertTrue(response.context["has_items"])

    def test_borrowing_sets_is_borrowing(self) -> None:
        lender = _make_user("flaglender")
        item = _make_item(lender)
        item.status = ItemStatus.BORROWED
        item.save()
        Transaction.objects.create(
            item=item,
            party1=lender,
            party2=self.user,
            status=TransactionStatus.COLLECTED,
            created_by=self.user,
            updated_by=self.user,
        )
        response = self.client.get(reverse("profile"))
        self.assertTrue(response.context["is_borrowing"])

    def test_active_lend_sets_is_lending(self) -> None:
        item = _make_item(self.user)
        item.status = ItemStatus.BORROWED
        item.save()
        borrower = _make_user("flagborrower")
        Transaction.objects.create(
            item=item,
            party1=self.user,
            party2=borrower,
            status=TransactionStatus.COLLECTED,
            created_by=self.user,
            updated_by=self.user,
        )
        response = self.client.get(reverse("profile"))
        self.assertTrue(response.context["is_lending"])
        self.assertTrue(response.context["has_items"])

    def test_returned_lend_does_not_set_is_lending(self) -> None:
        # Lent an item that's since been returned (now available again): the
        # modal must not still claim the user is lending it.
        item = _make_item(self.user)
        borrower = _make_user("flagreturner")
        Transaction.objects.create(
            item=item,
            party1=self.user,
            party2=borrower,
            status=TransactionStatus.RETURNED,
            created_by=self.user,
            updated_by=self.user,
        )
        response = self.client.get(reverse("profile"))
        self.assertFalse(response.context["is_lending"])
        self.assertTrue(response.context["has_items"])
