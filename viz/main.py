from pathlib import Path

from .loader import load_data
from .splitter import split_components
from .styler import assign_settlement_colours, assign_degrees
from .renderer import render

BASE_DIR = Path(__file__).parent.parent
NODES_FILE = BASE_DIR / "all-nodes.json"
EDGES_FILE = BASE_DIR / "all-edges.json"
OUTPUT = BASE_DIR / "graph.html"


def main():
    all_nodes, all_edges = load_data(NODES_FILE, EDGES_FILE)

    components = split_components(all_nodes, all_edges)

    colour_map = assign_settlement_colours(components)
    assign_degrees(components, colour_map)

    print(f"Components: {len(components)}")
    for i, c in enumerate(components):
        tag = " (heavy)" if c["size"] > 200 else ""
        print(f"  #{i+1}: {c['size']} nodes, {c['edge_count']} edges{tag}")

    html = render(components, colour_map)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"\nSaved: {OUTPUT}")
