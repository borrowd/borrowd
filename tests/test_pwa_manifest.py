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
        self.assertEqual(manifest["background_color"], "#ffffff")
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
        self.assertTrue(all("media" not in icon for icon in manifest["icons"]))
        self.assertTrue(all("-dark" not in icon["src"] for icon in manifest["icons"]))

    def test_manifest_icons_exist(self) -> None:
        static_dir = self.manifest_path.parent
        manifest = json.loads(self.manifest_path.read_text())

        for icon in manifest["icons"]:
            self.assertTrue((static_dir / icon["src"]).is_file(), icon["src"])

        self.assertTrue((static_dir / "favicon-dark.ico").is_file())

    def test_base_template_links_pwa_metadata(self) -> None:
        template = " ".join(self.base_template_path.read_text().split())

        self.assertIn(
            'data-color-scheme-light="#ffffff" data-color-scheme-dark="#0b0907"',
            template,
        )
        self.assertIn(
            "data-color-scheme-dark=\"{% url 'web-app-manifest' %}?color_scheme=dark&amp;v=4\"",
            template,
        )
        self.assertIn(
            "data-color-scheme-light=\"{% static 'icon-192.png' %}?v=4\"",
            template,
        )
        self.assertIn(
            "data-color-scheme-dark=\"{% static 'icon-dark-192.png' %}?v=4\"",
            template,
        )
        self.assertIn(
            "data-color-scheme-dark=\"{% static 'favicon-dark.ico' %}\"",
            template,
        )

    def test_base_template_exposes_install_prompt_controls(self) -> None:
        template = " ".join(self.base_template_path.read_text().split())

        self.assertIn("data-install-prompt hidden", template)
        self.assertIn("data-install-prompt-action", template)
        self.assertIn("data-install-prompt-dismiss", template)

    def test_manifest_uses_light_icons_by_default(self) -> None:
        response = self.client.get("/manifest.json")
        manifest = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        self.assertEqual(manifest["background_color"], "#ffffff")
        self.assertEqual(
            {(icon["src"], icon["purpose"]) for icon in manifest["icons"]},
            {
                ("/static/icon-maskable-192.png?v=4", "maskable"),
                ("/static/icon-maskable-512.png?v=4", "maskable"),
            },
        )
        self.assertIn("Sec-CH-Prefers-Color-Scheme", response["Vary"])

    def test_manifest_uses_dark_icons_when_requested(self) -> None:
        response = self.client.get(
            "/manifest.json",
            HTTP_SEC_CH_PREFERS_COLOR_SCHEME='"dark"',
        )
        manifest = json.loads(response.content)

        self.assertEqual(manifest["background_color"], "#0b0907")
        self.assertEqual(
            {(icon["src"], icon["purpose"]) for icon in manifest["icons"]},
            {
                ("/static/icon-maskable-dark-192.png?v=4", "maskable"),
                ("/static/icon-maskable-dark-512.png?v=4", "maskable"),
            },
        )

    def test_manifest_color_scheme_query_overrides_client_hint(self) -> None:
        response = self.client.get(
            "/manifest.json?color_scheme=dark",
            HTTP_SEC_CH_PREFERS_COLOR_SCHEME='"light"',
        )
        manifest = json.loads(response.content)

        self.assertEqual(manifest["background_color"], "#0b0907")
        self.assertIn(
            "/static/icon-maskable-dark-192.png?v=4",
            {i["src"] for i in manifest["icons"]},
        )

    def test_html_response_opts_in_to_color_scheme_client_hint(self) -> None:
        response = self.client.get("/accounts/login/")

        self.assertEqual(response["Accept-CH"], "Sec-CH-Prefers-Color-Scheme")

    @override_settings(BORROWD_BETA_ENABLED=True)
    def test_service_worker_is_served_directly_before_beta_access(self) -> None:
        response = self.client.get("/sw.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertContains(response, 'self.addEventListener("push"')

    @override_settings(BORROWD_BETA_ENABLED=True)
    def test_manifest_is_served_directly_before_beta_access(self) -> None:
        response = self.client.get(
            "/manifest.json",
            HTTP_SEC_CH_PREFERS_COLOR_SCHEME='"dark"',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
