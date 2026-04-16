"""E2E tests for the Portfolio (组合管理) page."""
from playwright.sync_api import expect


class TestPortfolioSmoke:
    """Smoke tests: page loads and sections are present."""

    def test_page_loads(self, page, server_url):
        """Heading should contain '组合'."""
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")
        heading = page.locator("h2")
        expect(heading).to_contain_text("组合")

    def test_sections_present(self, page, server_url):
        """'策略权重', '风控状态', 'NAV' sections should be visible."""
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")

        expect(page.locator("text=策略权重")).to_be_visible()
        expect(page.locator("text=风控状态")).to_be_visible()
        expect(page.locator("text=NAV")).to_be_visible()


class TestPortfolioFunctional:
    """Functional tests: seeded data rendered correctly."""

    def test_weights_table_visible(self, page, server_url):
        """Strategy names from seeded weights should be visible."""
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")

        # The weights section lists strategy names like "divergence"
        expect(page.get_by_text("divergence", exact=True).first).to_be_visible()

    def test_risk_status_visible(self, page, server_url):
        """Risk status should show '正常运行' or '已暂停交易'."""
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")

        # RiskStatus component shows either "正常运行" or "已暂停交易"
        risk_section = page.locator("text=风控状态").locator("..").locator("..")
        risk_text = risk_section.inner_text()
        assert "正常运行" in risk_text or "已暂停交易" in risk_text, (
            f"Expected risk status text, got: {risk_text}"
        )

    def test_rebalance_button_exists(self, page, server_url):
        """'再平衡' button should be visible."""
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")

        btn = page.locator("button", has_text="再平衡")
        expect(btn).to_be_visible()
