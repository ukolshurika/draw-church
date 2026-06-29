import json
from pathlib import Path

from viz.loader import load_data
from viz.splitter import split_components
from viz.styler import (
    assign_settlement_colours,
    assign_degrees,
    RELATION_COLORS,
    RECORD_COLORS,
    SETTLEMENT_PALETTE,
    NONE_SETTLEMENT_KEY,
)


class TestLoader:
    def test_load_returns_tuple(self, small_nodes, small_edges):
        nodes_path = Path(__file__).parent / "fixtures" / "small-nodes.json"
        edges_path = Path(__file__).parent / "fixtures" / "small-edges.json"
        result = load_data(nodes_path, edges_path)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], list)

    def test_load_content(self, small_nodes, small_edges):
        nodes_path = Path(__file__).parent / "fixtures" / "small-nodes.json"
        edges_path = Path(__file__).parent / "fixtures" / "small-edges.json"
        nodes, edges = load_data(nodes_path, edges_path)
        assert len(nodes) == 5
        assert len(edges) == 3
        assert nodes[0]["first_name"] == "Иван"
        assert edges[0]["relation"] == "child_of"


class TestSplitter:
    def test_returns_sorted_components(self, small_nodes, small_edges):
        components = split_components(small_nodes, small_edges)
        assert len(components) == 2

    def test_component_sizes(self, small_nodes, small_edges):
        components = split_components(small_nodes, small_edges)
        sizes = [c["size"] for c in components]
        assert sizes == [4, 1]

    def test_component_edge_counts(self, small_nodes, small_edges):
        components = split_components(small_nodes, small_edges)
        assert components[0]["edge_count"] == 3
        assert components[1]["edge_count"] == 0

    def test_nodes_in_component(self, small_nodes, small_edges):
        components = split_components(small_nodes, small_edges)
        node_ids = {n["id"] for n in components[0]["nodes"]}
        assert node_ids == {1, 2, 3, 4}
        assert components[1]["nodes"][0]["id"] == 5

    def test_edges_in_component(self, small_nodes, small_edges):
        components = split_components(small_nodes, small_edges)
        assert len(components[0]["edges"]) == 3
        assert components[1]["edges"] == []

    def test_correct_component_order(self, small_nodes, small_edges):
        components = split_components(small_nodes, small_edges)
        for i in range(len(components) - 1):
            assert components[i]["size"] >= components[i + 1]["size"]


class TestStyler:
    def test_colour_map_keys(self, small_components):
        colour_map = assign_settlement_colours(small_components)
        assert NONE_SETTLEMENT_KEY in colour_map
        assert colour_map[NONE_SETTLEMENT_KEY] == "#444444"

    def test_colour_map_has_settlements(self, small_components):
        colour_map = assign_settlement_colours(small_components)
        assert "Село А" in colour_map
        assert "Село Б" in colour_map
        assert "Село В" in colour_map

    def test_colour_map_palette_size(self, small_components):
        colour_map = assign_settlement_colours(small_components)
        assert len(colour_map) == 4  # 3 settlements + __none__

    def test_colour_from_palette(self, small_components):
        colour_map = assign_settlement_colours(small_components)
        for sett, colour in colour_map.items():
            if sett == NONE_SETTLEMENT_KEY:
                continue
            assert colour in SETTLEMENT_PALETTE

    def test_assign_degrees(self, small_components):
        colour_map = assign_settlement_colours(small_components)
        assign_degrees(small_components, colour_map)
        nodes = [n for c in small_components for n in c["nodes"]]
        for n in nodes:
            assert "_deg" in n
            assert "_settc" in n

    def test_degree_values(self, small_components):
        colour_map = assign_settlement_colours(small_components)
        assign_degrees(small_components, colour_map)
        nodes = [n for c in small_components for n in c["nodes"]]
        node_deg = {n["id"]: n["_deg"] for n in nodes}
        # Node 1: edges to 2 (child_of) and 4 (godparent_of) = degree 2
        assert node_deg[1] == 2
        # Node 2: edges to 1 (child_of) and 3 (married_to) = degree 2
        assert node_deg[2] == 2
        # Node 3: edge to 2 (married_to) = degree 1
        assert node_deg[3] == 1
        # Node 4: edge to 1 (godparent_of) = degree 1
        assert node_deg[4] == 1
        # Node 5: isolated = degree 0
        assert node_deg[5] == 0

    def test_settc_fallback(self, small_components):
        colour_map = assign_settlement_colours(small_components)
        assign_degrees(small_components, colour_map)
        nodes = [n for c in small_components for n in c["nodes"]]
        node_4 = next(n for n in nodes if n["id"] == 4)
        assert node_4["_settc"] == colour_map[NONE_SETTLEMENT_KEY]

    def test_relation_colors_defined(self):
        expected = ["child_of", "godparent_of", "married_to", "witnessed_for", "other"]
        for rel in expected:
            assert rel in RELATION_COLORS
            assert RELATION_COLORS[rel].startswith("#")

    def test_record_colors_defined(self):
        expected = ["Родившийся", "Бракосочетание"]
        for rec in expected:
            assert rec in RECORD_COLORS
            assert RECORD_COLORS[rec].startswith("#")


class TestRenderOutput:
    def test_html_contains_components(self, styled_small_components, small_colour_map):
        from viz.renderer import render
        html = render(styled_small_components, small_colour_map)
        assert "var COMPONENTS =" in html
        assert "var REL_COLORS =" in html
        assert "var REC_COLORS =" in html
        assert "var SETT_COLORS =" in html

    def test_html_comp_data(self, styled_small_components, small_colour_map):
        from viz.renderer import render
        html = render(styled_small_components, small_colour_map)
        # Extract COMPONENTS JS variable
        import re
        m = re.search(r'var COMPONENTS = (\[.*?\]);', html, re.DOTALL)
        assert m, "COMPONENTS not found in HTML"
        import json
        comps = json.loads(m.group(1))
        assert len(comps) == 2
        assert comps[0]["size"] == 4
        assert comps[1]["size"] == 1

    def test_html_has_event_handlers(self, styled_small_components, small_colour_map):
        from viz.renderer import render
        html = render(styled_small_components, small_colour_map)
        assert "network.on('click'" in html, "Click handler missing"
        assert "network.on('doubleClick'" in html, "DoubleClick handler missing"
        assert "network.on('stabilizationIterationsDone'" in html

    def test_html_has_detail_elements(self, styled_small_components, small_colour_map):
        from viz.renderer import render
        html = render(styled_small_components, small_colour_map)
        for el in ["det-name", "det-sett", "det-year", "det-type", "det-role"]:
            assert f'id="{el}"' in html, f"Missing {el}"

    def test_html_has_none_key(self, styled_small_components, small_colour_map):
        from viz.renderer import render
        html = render(styled_small_components, small_colour_map)
        assert NONE_SETTLEMENT_KEY in html or "__none__" in html

    def test_html_degrees_attached(self, styled_small_components, small_colour_map):
        from viz.renderer import render
        html = render(styled_small_components, small_colour_map)
        assert '"_deg":' in html or '"_deg"' in html

    def test_html_settc_attached(self, styled_small_components, small_colour_map):
        from viz.renderer import render
        html = render(styled_small_components, small_colour_map)
        assert '"_settc":' in html or '"_settc"' in html

    def test_no_stale_jinja2_tags(self, styled_small_components, small_colour_map):
        from viz.renderer import render
        html = render(styled_small_components, small_colour_map)
        assert "{{" not in html
        assert "{%" not in html

    def test_settc_colors_has_none(self, styled_small_components, small_colour_map):
        from viz.renderer import render
        html = render(styled_small_components, small_colour_map)
        import re
        m = re.search(r'var SETT_COLORS = (\{.*?\});', html, re.DOTALL)
        assert m
        import json
        sett = json.loads(m.group(1))
        assert NONE_SETTLEMENT_KEY in sett or "__none__" in sett
