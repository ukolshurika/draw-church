import argparse
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
    parser = argparse.ArgumentParser(description="Build graph HTML from nodes+edges")
    parser.add_argument("--nodes", type=Path, default=NODES_FILE,
                        help="Input nodes JSON file")
    parser.add_argument("--edges", type=Path, default=EDGES_FILE,
                        help="Input edges JSON file")
    parser.add_argument("--output", type=Path, default=OUTPUT,
                        help="Output HTML file")
    args = parser.parse_args()

    all_nodes, all_edges = load_data(args.nodes, args.edges)

    components = split_components(all_nodes, all_edges)

    colour_map = assign_settlement_colours(components)
    assign_degrees(components, colour_map)

    print(f"Components: {len(components)}")
    for i, c in enumerate(components):
        tag = " (heavy)" if c["size"] > 200 else ""
        print(f"  #{i+1}: {c['size']} nodes, {c['edge_count']} edges{tag}")

    html = render(components, colour_map)
    args.output.write_text(html, encoding="utf-8")
    print(f"\nSaved: {args.output}")
