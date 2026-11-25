from playwright.sync_api import Page, expect


class NotificationSettingsPage:
    """Settings > Notifications: one row per notification category, each
    with a "What's included" disclosure and one switch per channel."""

    def __init__(self, page: Page):
        self.page = page
        self.intro = page.get_by_text("Choose how you want to be notified.")

    def open(self, base_url: str):
        self.page.goto(
            f"{base_url}/settings/notifications/", wait_until="domcontentloaded"
        )
        expect(self.intro).to_be_visible()

    def row(self, slug: str):
        return self.page.locator(f"#notification-category-{slug}")

    def included_button(self, slug: str):
        return self.row(slug).get_by_role("button", name="What's included")

    def included_list(self, slug: str):
        return self.page.locator(f"#notification-category-{slug}-included")

    def switch(self, row_name: str, channel: str):
        return self.page.get_by_role("checkbox", name=f"{row_name}, {channel}")

    def set_switch(self, row_name: str, channel: str, on: bool):
        switch = self.switch(row_name, channel)
        # Each change posts to the bulk-toggle endpoint; wait for it so a
        # reload right after sees the saved value.
        with self.page.expect_response(
            lambda r: "/settings/notifications/bulk-toggle/" in r.url
        ) as response:
            switch.set_checked(on)
        assert response.value.status == 204
