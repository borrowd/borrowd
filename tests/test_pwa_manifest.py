import json
from pathlib import Path

from django.templatetags.static import static
from django.test import SimpleTestCase, override_settings

from borrowd_web.pwa import PWA_DARK_COLOR, PWA_ICON_VERSION, PWA_LIGHT_COLOR


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
        self.assertIn(
            {
                "src": "icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any",
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
            'content="{{ pwa_light_color }}" media="(prefers-color-scheme: light)"',
            template,
        )
        self.assertIn(
            'content="{{ pwa_dark_color }}" media="(prefers-color-scheme: dark)"',
            template,
        )
        self.assertIn(
            "data-color-scheme-dark=\"{% url 'web-app-manifest' %}?color_scheme=dark&amp;v={{ pwa_icon_version }}\"",
            template,
        )
        self.assertIn(
            'href="{% static \'icon-192.png\' %}?v={{ pwa_icon_version }}" media="(prefers-color-scheme: light)"',
            template,
        )
        self.assertIn(
            'href="{% static \'icon-dark-192.png\' %}?v={{ pwa_icon_version }}" media="(prefers-color-scheme: dark)"',
            template,
        )
        self.assertIn('media="(prefers-color-scheme: dark)"', template)

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
        self.assertEqual(manifest["theme_color"], "#ffffff")
        self.assertEqual(
            {(icon["src"], icon["purpose"]) for icon in manifest["icons"]},
            {
                (f"{static('icon-192.png')}?v={PWA_ICON_VERSION}", "any"),
                (f"{static('icon-512.png')}?v={PWA_ICON_VERSION}", "any"),
                (
                    f"{static('icon.svg')}?color_scheme=light&v={PWA_ICON_VERSION}",
                    "any",
                ),
                (
                    f"{static('icon-maskable-192.png')}?v={PWA_ICON_VERSION}",
                    "maskable",
                ),
                (
                    f"{static('icon-maskable-512.png')}?v={PWA_ICON_VERSION}",
                    "maskable",
                ),
            },
        )
        self.assertEqual(manifest["theme_color"], PWA_LIGHT_COLOR)
        self.assertEqual(response["Cache-Control"], "public, max-age=3600")

    def test_manifest_uses_dark_icons_when_requested(self) -> None:
        response = self.client.get(
            "/manifest.json?color_scheme=dark",
        )
        manifest = json.loads(response.content)

        self.assertEqual(manifest["background_color"], PWA_DARK_COLOR)
        self.assertEqual(manifest["theme_color"], PWA_DARK_COLOR)
        self.assertEqual(
            {(icon["src"], icon["purpose"]) for icon in manifest["icons"]},
            {
                (f"{static('icon-dark-192.png')}?v={PWA_ICON_VERSION}", "any"),
                (f"{static('icon-dark-512.png')}?v={PWA_ICON_VERSION}", "any"),
                (
                    f"{static('icon.svg')}?color_scheme=dark&v={PWA_ICON_VERSION}",
                    "any",
                ),
                (
                    f"{static('icon-maskable-dark-192.png')}?v={PWA_ICON_VERSION}",
                    "maskable",
                ),
                (
                    f"{static('icon-maskable-dark-512.png')}?v={PWA_ICON_VERSION}",
                    "maskable",
                ),
            },
        )

    def test_manifest_color_scheme_query_overrides_client_hint(self) -> None:
        response = self.client.get(
            "/manifest.json?color_scheme=dark",
        )
        manifest = json.loads(response.content)

        self.assertEqual(manifest["background_color"], PWA_DARK_COLOR)
        self.assertIn(
            f"{static('icon-maskable-dark-192.png')}?v={PWA_ICON_VERSION}",
            {i["src"] for i in manifest["icons"]},
        )

    @override_settings(BORROWD_BETA_ENABLED=True)
    def test_service_worker_is_served_directly_before_beta_access(self) -> None:
        response = self.client.get("/sw.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertContains(response, 'self.addEventListener("push"')

    @override_settings(BORROWD_BETA_ENABLED=True)
    def test_manifest_is_served_directly_before_beta_access(self) -> None:
        response = self.client.get(
            "/manifest.json?color_scheme=dark",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
