#!/usr/bin/env python3
"""Add `kum` edges (godparent → parent) to an existing nodes/edges dataset.

Reconstructs godparent–parent pairs within the same BIRTH entry directly from
the final nodes/edges files, so it preserves the result of the expensive
LLM/manual dedup exactly. Needed only for datasets built before the `kum`
relation was added to parsing/extract.py build_edges.

A kum edge (G → P) exists when a born person B has both a `godparent_of` edge
(G → B) and a `child_of` edge (B → P), and G, B and P all appear in the same
birth entry (shared entry_id in their sources). The shared-entry check filters
out pairings that only exist because a born person aggregated several records.

Usage:
  python3 add_kum_edges.py --nodes all-nodes.json --edges all-edges.json [--dry-run]
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).parent
NODES_PATH = BASE_DIR / "all-nodes.json"
EDGES_PATH = BASE_DIR / "all-edges.json"

ENTRY_RE = re.compile(r"entry_id=([\w-]+)")


def entry_ids(node: dict) -> set[str]:
    ids = set()
    for s in node.get("sources", []):
        m = ENTRY_RE.search(s.get("url", ""))
        if m:
            ids.add(m.group(1))
    return ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", type=Path, default=NODES_PATH)
    parser.add_argument("--edges", type=Path, default=EDGES_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    nodes = json.loads(args.nodes.read_text(encoding="utf-8"))
    edges = json.loads(args.edges.read_text(encoding="utf-8"))

    node_by_id = {n["id"]: n for n in nodes}
    eid_cache = {nid: entry_ids(n) for nid, n in node_by_id.items()}

    born_to_gods: dict[int, set[int]] = defaultdict(set)
    born_to_parents: dict[int, set[int]] = defaultdict(set)
    for e in edges:
        if e["relation"] == "godparent_of":
            born_to_gods[e["target_id"]].add(e["source_id"])
        elif e["relation"] == "child_of":
            born_to_parents[e["source_id"]].add(e["target_id"])

    existing = {(e["source_id"], e["target_id"], e["relation"]) for e in edges}
    new_edges = []
    seen = set()
    filtered = 0
    for born, gods in born_to_gods.items():
        for g in gods:
            for p in born_to_parents.get(born, ()):
                if g == p:
                    continue
                if not (eid_cache[g] & eid_cache[born] & eid_cache[p]):
                    filtered += 1
                    continue
                key = (g, p, "kum")
                if key in seen or key in existing:
                    continue
                seen.add(key)
                existing.add(key)
                new_edges.append({"source_id": g, "target_id": p, "relation": "kum"})

    print(f"Nodes: {len(nodes)}, edges before: {len(edges)}")
    print(f"Pair combinations without a shared birth entry (filtered): {filtered}")
    print(f"New kum edges to add: {len(new_edges)}")

    if args.dry_run:
        print("DRY RUN — not writing.")
        return

    edges.extend(new_edges)
    args.edges.write_text(
        json.dumps(edges, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved: {args.edges} ({len(edges)} edges)")


if __name__ == "__main__":
    main()
