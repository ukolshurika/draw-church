import json
from pathlib import Path


def load_data(nodes_path: Path, edges_path: Path) -> tuple[list[dict], list[dict]]:
    all_nodes = json.loads(nodes_path.read_text(encoding="utf-8"))
    all_edges = json.loads(edges_path.read_text(encoding="utf-8"))
    return all_nodes, all_edges
