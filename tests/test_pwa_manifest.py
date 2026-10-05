import json
from pathlib import Path

from django.test import SimpleTestCase


class PwaManifestTests(SimpleTestCase):
    manifest_path = Path(__file__).resolve().parent.parent / "static" / "manifest.json"
    base_template_path = (
        Path(__file__).resolve().parent.parent / "templates" / "base.html"
    )
    main_script_path = (
        Path(__file__).resolve().parent.parent / "static" / "js" / "main.js"
    )
    service_worker_path = (
        Path(__file__).resolve().parent.parent / "static" / "js" / "sw.js"
    )
    notification_preferences_path = (
        Path(__file__).resolve().parent.parent
        / "templates"
        / "notifications"
        / "preferences.html"
    )

    def test_manifest_defines_installable_app_identity_and_icons(self) -> None:
        manifest = json.loads(self.manifest_path.read_text())

        self.assertEqual(manifest["name"], "Borrow'd")
        self.assertEqual(manifest["short_name"], "Borrow'd")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["theme_color"], "#0b0907")
        self.assertEqual(manifest["background_color"], "#0b0907")
        self.assertIn(
            {
                "src": "icon-maskable-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "maskable",
            },
            manifest["icons"],
        )
        self.assertIn(
            {
                "src": "icon-maskable-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
            manifest["icons"],
        )

    def test_manifest_icons_exist(self) -> None:
        static_dir = self.manifest_path.parent
        manifest = json.loads(self.manifest_path.read_text())

        for icon in manifest["icons"]:
            self.assertTrue((static_dir / icon["src"]).is_file(), icon["src"])

    def test_base_template_links_pwa_metadata(self) -> None:
        template = self.base_template_path.read_text()

        self.assertIn('<meta name="theme-color" content="#0b0907" />', template)
        self.assertIn(
            '<link rel="manifest" href="{% static \'manifest.json\' %}">', template
        )
        self.assertIn(
            '<link rel="apple-touch-icon" href="{% static \'icon-192.png\' %}">',
            template,
        )

    def test_service_worker_is_registered_site_wide(self) -> None:
        main_script = self.main_script_path.read_text()

        self.assertIn('if ("serviceWorker" in navigator)', main_script)
        self.assertIn('navigator.serviceWorker.register("/sw.js")', main_script)

    def test_service_worker_passes_fetch_requests_through_and_keeps_push_handlers(
        self,
    ) -> None:
        service_worker = self.service_worker_path.read_text()

        self.assertIn('self.addEventListener("fetch"', service_worker)
        self.assertIn("event.respondWith(fetch(event.request));", service_worker)
        self.assertIn('self.addEventListener("push"', service_worker)
        self.assertIn('self.addEventListener("notificationclick"', service_worker)

    def test_push_preferences_reuse_site_wide_service_worker(self) -> None:
        notification_preferences = self.notification_preferences_path.read_text()

        self.assertIn("navigator.serviceWorker.ready", notification_preferences)
        self.assertNotIn("serviceWorker.register(", notification_preferences)
        self.assertNotIn(".unregister()", notification_preferences)
