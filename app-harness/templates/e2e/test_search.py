"""Example E2E test — search flow with a deterministic setup (intercepted network).

To run:
    pytest tests/e2e -q

Flaky triage (Lesson 10):
    pytest tests/e2e/test_search.py --trace=retain-on-failure
    playwright show-trace <artifact>.zip
"""

import pytest
from playwright.sync_api import Page, expect

from pages.search_page import SearchPage

FIXTURE_RESULTS = [
    {"id": "1", "title": "Honda Civic 2023", "price": "R$ 120.000"},
    {"id": "2", "title": "Toyota Corolla 2024", "price": "R$ 135.000"},
]


@pytest.fixture
def search_page(page: Page) -> SearchPage:
    # Intercepts the search: deterministic response, no dependency on the API
    page.route(
        "**/api/v1/search?*",
        lambda route: route.fulfill(json={"results": FIXTURE_RESULTS}),
    )
    page.goto("http://localhost:3000")
    return SearchPage(page)


def test_busca_retorna_resultados(search_page: SearchPage) -> None:
    search_page.search("civic")
    expect(search_page.search_input).to_have_value("civic")
    assert search_page.has_results()
    assert search_page.result_count() == 2


def test_busca_vazia_mostra_empty_state(search_page: SearchPage) -> None:
    search_page.page.route(
        "**/api/v1/search?*",
        lambda route: route.fulfill(json={"results": []}),
    )
    search_page.search("zzzz")
    assert not search_page.has_results()
