#!/usr/bin/env python3
"""Re-deduplicate persons in all-nodes.json after geo normalization.

Run this AFTER normalize_geo.py to merge persons whose settlement names
became identical after normalization (previously different raw strings
blocked dedup during the initial parse.py run).
"""
import json
import sys
from pathlib import Path
from parsing.dedup import deduplicate

BASE_DIR = Path(__file__).parent
NODES_PATH = BASE_DIR / "all-nodes.json"
EDGES_PATH = BASE_DIR / "all-edges.json"

if __name__ == "__main__":
    nodes = json.loads(NODES_PATH.read_text(encoding="utf-8"))
    edges = json.loads(EDGES_PATH.read_text(encoding="utf-8"))

    print(f"Loaded: {len(nodes)} nodes, {len(edges)} edges")

    # Assign _temp_id for dedup function
    for n in nodes:
        n["_temp_id"] = n["id"]

    unique, tid_map = deduplicate(nodes)
    print(f"After re-dedup: {len(unique)} nodes (was {len(nodes)})")

    # Remap edges
    final_edges = []
    for e in edges:
        s = tid_map.get(e["source_id"])
        t = tid_map.get(e["target_id"])
        if s and t and s != t:
            final_edges.append({"source_id": s, "target_id": t, "relation": e["relation"]})

    # Deduplicate edges
    seen = set()
    deduped_edges = []
    for e in final_edges:
        key = (e["source_id"], e["target_id"], e["relation"])
        if key not in seen:
            seen.add(key)
            deduped_edges.append(e)

    print(f"Edges: {len(deduped_edges)} (was {len(edges)})")

    NODES_PATH.write_text(
        json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    EDGES_PATH.write_text(
        json.dumps(deduped_edges, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Saved: {NODES_PATH.name} ({len(unique)} nodes)")
    print(f"Saved: {EDGES_PATH.name} ({len(deduped_edges)} edges)")
    print("Done!")
