"""Browser-level tests via Playwright.

Requires: pip install pytest-playwright
Runs: playwright install chromium

Generates graph.html from small fixture data, opens in headless Chromium,
and verifies click/double-click behaviour.
"""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect

from viz.renderer import render
from viz.styler import NONE_SETTLEMENT_KEY

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"


# ── helpers ──────────────────────────────────────────────────────────

def _build_html():
    """Render graph.html from the small fixture data (no styling needed)."""
    from viz.loader import load_data
    from viz.splitter import split_components
    from viz.styler import assign_settlement_colours, assign_degrees

    nodes, edges = load_data(FIXTURES / "small-nodes.json", FIXTURES / "small-edges.json")
    components = split_components(nodes, edges)
    colour_map = assign_settlement_colours(components)
    assign_degrees(components, colour_map)
    return render(components, colour_map)


# ── fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def graph_html():
    return _build_html()


@pytest.fixture(scope="session")
def graph_html_path(graph_html, tmp_path_factory):
    p = tmp_path_factory.mktemp("viztest") / "graph.html"
    p.write_text(graph_html, encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture(scope="module")
def page(browser, graph_html_path):
    p = browser.new_page(viewport={"width": 1280, "height": 720})
    p.goto(f"file://{graph_html_path}")
    # Wait for vis-network to finish stabilising
    p.wait_for_function(
        "typeof network !== 'undefined' && network !== null",
        timeout=30000,
    )
    p.wait_for_function(
        "document.getElementById('loading').classList.contains('hidden')",
        timeout=30000,
    )
    yield p
    p.close()


# ── structural checks (no browser) ──────────────────────────────────

class TestHtmlStructure:
    """Tests on the raw HTML string (fast, no browser)."""

    def test_components_embedded(self, graph_html):
        """COMPONENTS var must contain the 2 small components."""
        m = re.search(r"var COMPONENTS = (\[.*?\]);", graph_html, re.DOTALL)
        assert m
        comps = json.loads(m.group(1))
        assert len(comps) == 2
        assert comps[0]["size"] == 4
        assert comps[1]["size"] == 1

    def test_deg_and_settc_on_nodes(self, graph_html):
        """Every node in the JSON must carry _deg and _settc."""
        m = re.search(r"var COMPONENTS = (\[.*?\]);", graph_html, re.DOTALL)
        comps = json.loads(m.group(1))
        for c in comps:
            for n in c["nodes"]:
                assert "_deg" in n, f"node {n['id']} missing _deg"
                assert "_settc" in n, f"node {n['id']} missing _settc"

    def test_sett_colors_has_none(self, graph_html):
        m = re.search(r"var SETT_COLORS = (\{.*?\});", graph_html, re.DOTALL)
        sett = json.loads(m.group(1))
        assert "__none__" in sett
        assert sett["__none__"] == "#444444"

    def test_event_handlers_defined(self, graph_html):
        assert "network.on('click'" in graph_html
        assert "network.on('doubleClick'" in graph_html
        assert "network.on('deselectNode'" in graph_html

    def test_detail_panel_elements(self, graph_html):
        for el in ["det-name", "det-sett", "det-year", "det-type", "det-role"]:
            assert f'id="{el}"' in graph_html, f"Missing #{el}"

    def test_physics_frozen_after_stabilization(self, graph_html):
        assert "setPhysics(false)" in graph_html
        assert "var physicsOn = false" in graph_html

    def test_no_css_keyframe_animation(self, graph_html):
        assert "@keyframes" not in graph_html, (
            "CSS @keyframes dots does not work cross-browser; use JS instead"
        )

    def test_csv_injection_escaped(self, graph_html):
        """csvEsc must prefix =, +, -, @ with tab."""
        csv_src = graph_html.split("function csvEsc")[1].split("function")[0]
        assert r"/^[=+\-@\t]" in csv_src

    def test_esc_declared_once(self, graph_html):
        assert graph_html.count("function esc(") == 1

    def test_detail_uses_structured_data(self, graph_html):
        """Detail panel must NOT parse _tip — must use node fields directly."""
        click_section = graph_html.split("network.on('click'")[1].split("network.on('deselectNode'")[0]
        assert "node._settlement" in click_section
        assert "node._year" in click_section
        assert "node._record_type" in click_section
        assert "_tip.split" not in click_section

    def test_loading_animation_uses_js(self, graph_html):
        assert "var loadingTimer" in graph_html
        assert "setInterval" in graph_html


# ── browser behaviour tests ─────────────────────────────────────────

class TestGraphBehaviour:
    """Live browser tests via Playwright."""

    def test_page_loads(self, page):
        assert "Метрические книги" in page.title()
        header = page.locator("h1")
        expect(header).to_have_text("Метрики")

    def test_component_selector_present(self, page):
        select = page.locator("#comp")
        expect(select).to_be_visible()
        options = select.locator("option").all()
        assert len(options) == 2

    def test_initial_node_count(self, page):
        stats = page.locator("#stats")
        assert "4 узлов" in stats.text_content() or "4 узла" in stats.text_content()

    def test_single_click_shows_detail(self, page):
        """Click a node programmatically via vis-network API and check sidebar."""
        detail = page.locator("#detail")
        expect(detail).not_to_be_visible()

        page.evaluate("""
            var nodeId = allNodesDs.get()[0].id;
            network.emit('click', {
                nodes: [nodeId],
                edges: [],
                pointer: { DOM: { x: 0, y: 0 }, canvas: { x: 0, y: 0 } },
                event: { type: 'click' }
            });
        """)
        page.wait_for_timeout(200)
        expect(detail).to_be_visible()

        name = page.locator("#det-name")
        assert "Иван" in name.text_content()

    def test_single_click_shows_patronymic(self, page):
        page.evaluate("""
            var nodeId = allNodesDs.get()[0].id;
            network.emit('click', {
                nodes: [nodeId],
                edges: [],
                pointer: { DOM: { x: 0, y: 0 }, canvas: { x: 0, y: 0 } },
                event: { type: 'click' }
            });
        """)
        page.wait_for_timeout(200)
        name = page.locator("#det-name")
        assert "Петров" in name.text_content()

    def test_click_on_isolated_node(self, page):
        """Node 5 (Анна) is in component #2 (1 node, no edges)."""
        page.evaluate("loadComponent(1)")
        page.wait_for_timeout(1000)

        page.evaluate("""
            var nodeId = allNodesDs.get()[0].id;
            network.emit('click', {
                nodes: [nodeId],
                edges: [],
                pointer: { DOM: { x: 0, y: 0 }, canvas: { x: 0, y: 0 } },
                event: { type: 'click' }
            });
        """)
        page.wait_for_timeout(300)

        detail = page.locator("#detail")
        expect(detail).to_be_visible()
        name = page.locator("#det-name")
        assert "Анна" in name.text_content()

        # Switch back to component 1 for subsequent tests
        page.evaluate("loadComponent(0)")
        page.wait_for_timeout(1000)

    def test_double_click_enters_focus_mode(self, page):
        page.evaluate("loadComponent(0)")
        page.wait_for_timeout(1000)

        focus_bar = page.locator("#focus-bar")
        expect(focus_bar).not_to_be_visible()

        page.evaluate("""
            var nodeId = allNodesDs.get()[0].id;
            network.emit('doubleClick', {
                nodes: [nodeId],
                edges: [],
                pointer: { DOM: { x: 0, y: 0 }, canvas: { x: 0, y: 0 } },
                event: { type: 'click' }
            });
        """)
        page.wait_for_timeout(300)
        expect(focus_bar).to_be_visible()

        focus_name = focus_bar.locator(".focus-name")
        assert "Иван" in focus_name.text_content()

        page.evaluate("exitFocus()")
        page.wait_for_timeout(200)
        expect(focus_bar).not_to_be_visible()

    def test_focus_mode_with_hop_slider(self, page):
        page.evaluate("loadComponent(0)")
        page.wait_for_timeout(1000)

        page.evaluate("""
            focusHop = 1;
            var nodeId = allNodesDs.get()[0].id;
            network.emit('doubleClick', {
                nodes: [nodeId],
                edges: [],
                pointer: { DOM: { x: 0, y: 0 }, canvas: { x: 0, y: 0 } },
                event: { type: 'click' }
            });
        """)
        page.wait_for_timeout(300)

        visible_count = page.evaluate("""
            allNodesDs.get().filter(function(n){ return !n.hidden; }).length
        """)
        # With hop=1 from node 1, we should see node 1 + its direct neighbours (2, 4) = 3
        assert visible_count == 3, f"Expected 3 visible nodes with hop=1, got {visible_count}"

        page.evaluate("exitFocus()")
        page.wait_for_timeout(200)

    def test_esc_exits_focus(self, page):
        page.evaluate("loadComponent(0)")
        page.wait_for_timeout(1000)

        page.evaluate("""
            var nodeId = allNodesDs.get()[0].id;
            network.emit('doubleClick', {
                nodes: [nodeId],
                edges: [],
                pointer: { DOM: { x: 0, y: 0 }, canvas: { x: 0, y: 0 } },
                event: { type: 'click' }
            });
        """)
        page.wait_for_timeout(300)

        focus_bar = page.locator("#focus-bar")
        expect(focus_bar).to_be_visible()

        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        expect(focus_bar).not_to_be_visible()

    def test_filter_buttons_work(self, page):
        page.evaluate("loadComponent(0)")
        page.wait_for_timeout(1000)

        btn = page.locator("#filt-birth")
        btn.click()
        page.wait_for_timeout(300)

        visible = page.evaluate("""
            allNodesDs.get().filter(function(n){ return !n.hidden; }).map(function(n){ return n._record_type; })
        """)
        for rec in visible:
            assert rec == "Родившийся", f"Expected only 'Родившийся', got {rec}"

        # Reset
        page.locator("#filt-all").click()
        page.wait_for_timeout(300)

    def test_search_filters_nodes(self, browser, graph_html_path):
        # Fresh page to avoid state coupling with other tests
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(f"file://{graph_html_path}")
        page.wait_for_function(
            "typeof network !== 'undefined' && network !== null", timeout=30000
        )
        page.wait_for_function(
            "document.getElementById('loading').classList.contains('hidden')", timeout=30000
        )

        page.evaluate("""
            document.getElementById('search').value = 'Мария';
            clearTimeout(searchTimer);
            doFilter();
        """)
        page.wait_for_timeout(300)

        visible_first = page.evaluate("""
            allNodesDs.get().filter(function(n){ return !n.hidden; }).map(function(n){ return n._first_name; })
        """)
        assert "Мария" in visible_first
        assert "Иван" not in visible_first

        page.close()

    def test_right_panel_shows_visible_nodes(self, page):
        page.evaluate("loadComponent(0)")
        page.wait_for_timeout(1000)

        page.evaluate("""
            var nodeId = allNodesDs.get()[0].id;
            network.emit('doubleClick', {
                nodes: [nodeId],
                edges: [],
                pointer: { DOM: { x: 0, y: 0 }, canvas: { x: 0, y: 0 } },
                event: { type: 'click' }
            });
        """)
        page.wait_for_timeout(300)

        rp = page.locator("#right-panel")
        expect(rp).to_be_visible()

        page.evaluate("exitFocus()")
        page.wait_for_timeout(200)
