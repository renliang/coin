"""E2E tests for the Sentiment (舆情分析) page."""
from playwright.sync_api import expect


class TestSentimentSmoke:
    """Smoke tests: page structure is correct."""

    def test_page_loads(self, page, server_url):
        """Heading should contain '舆情'."""
        page.goto(f"{server_url}/app/sentiment")
        page.wait_for_load_state("networkidle")
        heading = page.locator("h2")
        expect(heading).to_contain_text("舆情")

    def test_sections_present(self, page, server_url):
        """'情绪信号', '情绪趋势', '原始数据' sections should be visible."""
        page.goto(f"{server_url}/app/sentiment")
        page.wait_for_load_state("networkidle")

        expect(page.locator("text=情绪信号")).to_be_visible()
        expect(page.locator("text=情绪趋势")).to_be_visible()
        expect(page.locator("text=原始数据")).to_be_visible()


class TestSentimentFunctional:
    """Functional tests: seeded data renders correctly."""

    def test_signal_table_has_rows(self, page, server_url):
        """Signal table should have visible rows from seeded data."""
        page.goto(f"{server_url}/app/sentiment")
        page.wait_for_load_state("networkidle")

        rows = page.locator("table tbody tr")
        expect(rows.first).to_be_visible()
        assert rows.count() >= 1

    def test_source_filter_works(self, page, server_url):
        """Clicking 'twitter' filter button should update items list."""
        page.goto(f"{server_url}/app/sentiment")
        page.wait_for_load_state("networkidle")

        # Click the "twitter" filter button
        twitter_btn = page.locator("button", has_text="twitter")
        expect(twitter_btn).to_be_visible()
        twitter_btn.click()

        # Wait for the API call to complete
        page.wait_for_timeout(1000)

        # After filtering, all visible source labels in items should be "twitter"
        # The items section shows source labels as <span> with text matching the source
        items_section = page.locator("text=原始数据").locator("..").locator("..")
        source_labels = items_section.locator("span:text-is('twitter')")
        # At least one twitter item should be visible
        expect(source_labels.first).to_be_visible()
