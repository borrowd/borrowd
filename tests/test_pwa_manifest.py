import json
from pathlib import Path

from django.test import SimpleTestCase, override_settings


class PwaManifestTests(SimpleTestCase):
    manifest_path = Path(__file__).resolve().parent.parent / "static" / "manifest.json"
    base_template_path = (
        Path(__file__).resolve().parent.parent / "templates" / "base.html"
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
        self.assertEqual(
            {
                icon["src"]
                for icon in manifest["icons"]
                if icon.get("media") == "(prefers-color-scheme: dark)"
            },
            {
                "icon-dark-192.png",
                "icon-dark-512.png",
                "icon-maskable-dark-192.png",
                "icon-maskable-dark-512.png",
            },
        )

    def test_manifest_icons_exist(self) -> None:
        static_dir = self.manifest_path.parent
        manifest = json.loads(self.manifest_path.read_text())

        for icon in manifest["icons"]:
            self.assertTrue((static_dir / icon["src"]).is_file(), icon["src"])

        self.assertTrue((static_dir / "favicon-dark.ico").is_file())

    def test_base_template_links_pwa_metadata(self) -> None:
        template = " ".join(self.base_template_path.read_text().split())

        self.assertIn('<meta name="theme-color" content="#0b0907" />', template)
        self.assertIn(
            '<link rel="manifest" href="{% static \'manifest.json\' %}">', template
        )
        self.assertIn(
            '<link rel="apple-touch-icon" href="{% static \'icon-192.png\' %}">',
            template,
        )
        self.assertIn(
            '<link rel="apple-touch-icon" href="{% static \'icon-dark-192.png\' %}" media="(prefers-color-scheme: dark)">',
            template,
        )
        self.assertIn(
            '<link rel="icon" href="{% static \'favicon-dark.ico\' %}" sizes="32x32" media="(prefers-color-scheme: dark)">',
            template,
        )

    def test_base_template_exposes_install_prompt_controls(self) -> None:
        template = " ".join(self.base_template_path.read_text().split())

        self.assertIn("data-install-prompt hidden", template)
        self.assertIn("data-install-prompt-action", template)
        self.assertIn("data-install-prompt-dismiss", template)

    @override_settings(BORROWD_BETA_ENABLED=True)
    def test_service_worker_is_served_directly_before_beta_access(self) -> None:
        response = self.client.get("/sw.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertContains(response, 'self.addEventListener("push"')
