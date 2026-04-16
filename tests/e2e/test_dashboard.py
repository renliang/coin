"""E2E tests for the Dashboard (DashboardV2) page."""
from playwright.sync_api import expect


class TestDashboardSmoke:
    """Basic smoke tests: page loads, key elements visible."""

    def test_page_loads(self, app_page):
        """Dashboard h2 should contain '总览'."""
        heading = app_page.locator("h2")
        expect(heading).to_contain_text("总览")

    def test_stat_cards_present(self, app_page):
        """At least one rounded-xl card should be visible."""
        cards = app_page.locator(".rounded-xl")
        expect(cards.first).to_be_visible()
        assert cards.count() >= 1


class TestDashboardFunctional:
    """Functional tests: data actually rendered from seeded DB."""

    def test_nav_value_displayed(self, app_page):
        """'总净值' card should show a numeric value, not '--'."""
        # StatCard renders: label in <p class="text-xs text-slate-500 mb-1">
        # and value in the next <p class="text-xl ...">
        card = app_page.locator("text=总净值").locator("..")
        value_el = card.locator("p.text-xl")
        expect(value_el).to_be_visible()
        text = value_el.inner_text()
        assert text != "--", f"NAV should be a number, got '{text}'"

    def test_sentiment_indicator_present(self, app_page):
        """'市场情绪' card should show 偏多/偏空/中性."""
        card = app_page.locator("text=市场情绪").locator("..")
        # The sub text shows the sentiment label
        expect(card).to_be_visible()
        card_text = card.inner_text()
        assert any(label in card_text for label in ("偏多", "偏空", "中性")), (
            f"Expected sentiment label in card text, got: {card_text}"
        )
