import math
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

import polib
from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from borrowd_users.models import BorrowdUser

PSEUDO_LOCALE = "xx"


def pseudo_translate(text: str) -> str:
    return f"[{text}{'~' * math.ceil(len(text) * 0.3)}]"


def build_pseudo_catalog(locale_dir: Path) -> None:
    # makemessages deletes locale/django.pot, which is committed for Weblate.
    pot_path = settings.BASE_DIR / "locale" / "django.pot"
    pot_content = pot_path.read_bytes()
    try:
        call_command(
            "makemessages",
            locale=[PSEUDO_LOCALE],
            ignore_patterns=[".venv", "node_modules"],
            verbosity=0,
        )
    finally:
        pot_path.write_bytes(pot_content)
    # makemessages always writes to the project's own locale/, ignoring LOCALE_PATHS.
    catalog_dir = locale_dir / PSEUDO_LOCALE
    shutil.move(settings.BASE_DIR / "locale" / PSEUDO_LOCALE, catalog_dir)
    po_path = catalog_dir / "LC_MESSAGES" / "django.po"
    catalog = polib.pofile(str(po_path))
    # A new catalog's placeholder Plural-Forms header can't be parsed when loaded.
    catalog.metadata["Plural-Forms"] = "nplurals=2; plural=(n != 1);"
    for entry in catalog:
        if entry.msgid_plural:
            entry.msgstr_plural = {
                0: pseudo_translate(entry.msgid),
                1: pseudo_translate(entry.msgid_plural),
            }
        else:
            entry.msgstr = pseudo_translate(entry.msgid)
    catalog.save_as_mofile(str(po_path.with_suffix(".mo")))


@skipUnless(shutil.which("xgettext"), "makemessages needs GNU gettext")
class PseudoLocaleRenderingTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        locale_dir = TemporaryDirectory()
        cls.addClassCleanup(locale_dir.cleanup)
        overrides = override_settings(
            LOCALE_PATHS=[locale_dir.name],
            LANGUAGES=[("en", "English"), (PSEUDO_LOCALE, "Pseudo")],
        )
        overrides.enable()
        cls.addClassCleanup(overrides.disable)
        build_pseudo_catalog(Path(locale_dir.name))

    def test_page_renders_pseudo_translated_text(self) -> None:
        self.client.force_login(BorrowdUser.objects.create(username="pseudo"))
        response = self.client.get(
            reverse("notification-inbox"), HTTP_ACCEPT_LANGUAGE=PSEUDO_LOCALE
        )
        self.assertContains(response, pseudo_translate("No notifications yet."))


class ProductionLanguageTests(TestCase):
    def test_pseudo_locale_request_gets_clean_english(self) -> None:
        self.assertNotIn(PSEUDO_LOCALE, dict(settings.LANGUAGES))
        self.client.force_login(BorrowdUser.objects.create(username="english"))
        response = self.client.get(
            reverse("notification-inbox"), HTTP_ACCEPT_LANGUAGE=PSEUDO_LOCALE
        )
        self.assertContains(response, "No notifications yet.")
        self.assertNotContains(response, "[No notifications")
