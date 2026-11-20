"""Example Page Object Model (POM) — the pattern required by the qa-playwright-e2e skill.

Rules (Lesson 10):
- SEMANTIC locators: get_by_role / get_by_label — never fragile CSS/XPath.
- Each screen = one class; each flow = one reusable method.
- Network interception for deterministic setups.
"""

from playwright.sync_api import Page


class SearchPage:
    def __init__(self, page: Page):
        self.page = page
        # Semantic locators — the only points of contact with the DOM
        self.search_input = page.get_by_role("searchbox", name="Buscar veículos")
        self.search_button = page.get_by_role("button", name="Buscar")
        self.result_list = page.get_by_role("list", name="Resultados")
        self.empty_state = page.get_by_role("region", name="Sem resultados")

    def search(self, term: str) -> "SearchPage":
        self.search_input.fill(term)
        self.search_button.click()
        self.page.wait_for_load_state("networkidle")
        return self

    def has_results(self) -> bool:
        return self.result_list.is_visible() and not self.empty_state.is_visible()

    def result_count(self) -> int:
        return self.result_list.get_by_role("listitem").count()
