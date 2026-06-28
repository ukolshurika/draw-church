#!/usr/bin/env python3
"""
Manual person merging tool for draw-church.

Usage:
  python3 merge_persons.py merge <source_id> <target_id> [--reason "text"]
      — Merge source person into target person; record in manifest.

  python3 merge_persons.py apply [--manifest manual-merges.json]
      — Re-apply all recorded merges after rebuild (resolves by entry_id).

  python3 merge_persons.py list
      — Show recorded merges.

  python3 merge_persons.py undo
      — Interactive: select a recorded merge to undo (restore from backup).

Manifest file: manual-merges.json — stores merges keyed by stable entry_id
so they can be re-applied after `python3 parse.py` rerun.
"""
import json, re, sys, shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent
NODES_PATH = BASE_DIR / "all-nodes.json"
EDGES_PATH = BASE_DIR / "all-edges.json"
MANIFEST_PATH = BASE_DIR / "manual-merges.json"
BACKUP_DIR = BASE_DIR / ".merge-backups"

ENTRY_ID_RE = re.compile(r"entry_id=([\w-]+)")


# ── helpers ──────────────────────────────────────────────────────

def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(obj, path):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def entry_ids_from_node(node):
    """Extract stable entry_ids from a person's archive_urls."""
    ids = set()
    for url in node.get("archive_urls", []):
        m = ENTRY_ID_RE.search(url)
        if m:
            ids.add(m.group(1))
    return ids


def find_node_by_entry_id(nodes, entry_ids):
    """Return the first node whose archive_urls contain any of the given entry_ids."""
    for n in nodes:
        if entry_ids_from_node(n) & entry_ids:
            return n
    return None


def backup():
    """Backup current data files before modifying."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for fname in ("all-nodes.json", "all-edges.json", "manual-merges.json"):
        src = BASE_DIR / fname
        if src.exists():
            dst = BACKUP_DIR / f"{ts}_{fname}"
            shutil.copy2(src, dst)
    print(f"  Backup saved to {BACKUP_DIR}/{ts}_*")


# ── merge logic ──────────────────────────────────────────────────

def merge_persons(nodes, edges, source_id, target_id):
    """Merge source into target in-place. Returns (source_node, target_info_pre_merge)."""
    src = None
    tgt = None
    for n in nodes:
        if n["id"] == source_id:
            src = n
        if n["id"] == target_id:
            tgt = n

    if not src:
        print(f"  ✗ Source person id={source_id} not found")
        return None, None
    if not tgt:
        print(f"  ✗ Target person id={target_id} not found")
        return None, None
    if source_id == target_id:
        print("  ✗ source_id == target_id, nothing to do")
        return None, None

    tgt_pre = {
        "archive_urls": list(tgt.get("archive_urls", [])),
        "id": tgt["id"],
        "first_name": tgt.get("first_name", ""),
        "patronymic": tgt.get("patronymic", ""),
        "surname": tgt.get("surname"),
    }

    # Merge scalar fields (keep target's, fill nulls from source)
    for field in ("first_name", "patronymic", "surname", "year",
                  "relation_type", "record_type", "landowner", "settlement"):
        if tgt.get(field) in (None, "", 0) and src.get(field) not in (None, "", 0):
            tgt[field] = src[field]

    # Union of list fields
    for field in ("all_roles", "all_record_types"):
        combined = list(dict.fromkeys(tgt.get(field, []) + src.get(field, [])))
        tgt[field] = combined

    for field in ("archive_urls",):
        seen = set(tgt.get(field, []))
        for item in src.get(field, []):
            if item not in seen:
                tgt.setdefault(field, []).append(item)
                seen.add(item)

    # Sources — deduplicate by full dict equality
    src_sources = src.get("sources", [])
    tgt_sources = tgt.get("sources", [])
    tgt_source_set = {json.dumps(s, sort_keys=True) for s in tgt_sources}
    for s in src_sources:
        key = json.dumps(s, sort_keys=True)
        if key not in tgt_source_set:
            tgt_sources.append(s)
            tgt_source_set.add(key)

    # Remove source from nodes list
    nodes[:] = [n for n in nodes if n["id"] != source_id]

    # Rewire edges
    new_edges = []
    seen_edges = set()
    for e in edges:
        src_id = target_id if e["source_id"] == source_id else e["source_id"]
        tgt_id = target_id if e["target_id"] == source_id else e["target_id"]
        if src_id == tgt_id:
            continue  # drop self-loops
        key = (src_id, tgt_id, e["relation"])
        if key not in seen_edges:
            seen_edges.add(key)
            new_edges.append({"source_id": src_id, "target_id": tgt_id, "relation": e["relation"]})

    edges[:] = new_edges

    print(f"  ✓ Merged id={source_id} → id={target_id}")
    print(f"    Target now: {tgt.get('first_name')} {tgt.get('patronymic')} {tgt.get('surname') or ''}")
    print(f"    Roles: {tgt['all_roles']}")
    return src, tgt_pre


def record_merge(manifest, src, tgt_pre_merge, reason=""):
    """Record merge in manifest using stable entry_ids (captured before merge)."""
    src_ids = entry_ids_from_node(src)
    tgt_ids = entry_ids_from_node(tgt_pre_merge)
    if not src_ids:
        print(f"  ⚠ Source id={src['id']} has no entry_ids; merge will not be reproducible after rebuild")
    if not tgt_ids:
        print(f"  ⚠ Target id={tgt_pre_merge['id']} has no entry_ids; merge will not be reproducible after rebuild")

    record = {
        "source_entry_ids": sorted(src_ids),
        "target_entry_ids": sorted(tgt_ids),
        "source_id": src["id"],
        "target_id": tgt_pre_merge["id"],
        "source_label": f"{src.get('first_name','')} {src.get('patronymic','')} {src.get('surname','') or ''}".strip(),
        "target_label": f"{src.get('first_name','')} {src.get('patronymic','')} {src.get('surname','') or ''}".strip(),
        "reason": reason or "(no reason given)",
    }

    # Check for duplicate
    for existing in manifest:
        if existing["source_entry_ids"] == record["source_entry_ids"]:
            print("  ⚠ Merge already recorded, skipping manifest append")
            return

    manifest.append(record)
    print(f"  ✓ Recorded in manifest ({len(manifest)} total)")
    dump_json(manifest, MANIFEST_PATH)


# ── commands ────────────────────────────────────────────────────

def cmd_merge(args):
    if len(args) < 2:
        print("Usage: merge_persons.py merge <source_id> <target_id> [--reason '...']")
        sys.exit(1)

    source_id = int(args[0])
    target_id = int(args[1])
    reason = ""
    if "--reason" in args:
        ri = args.index("--reason")
        if ri + 1 < len(args):
            reason = args[ri + 1]

    nodes = load_json(NODES_PATH)
    edges = load_json(EDGES_PATH)
    manifest = load_json(MANIFEST_PATH) if MANIFEST_PATH.exists() else []

    backup()

    src, tgt_pre = merge_persons(nodes, edges, source_id, target_id)
    if src is None:
        sys.exit(1)

    dump_json(nodes, NODES_PATH)
    dump_json(edges, EDGES_PATH)
    print(f"  Nodes: {len(nodes)}, Edges: {len(edges)}")

    record_merge(manifest, src, tgt_pre, reason)


def cmd_apply(args):
    manifest_path_str = args[0] if args else str(MANIFEST_PATH)
    manifest_path = Path(manifest_path_str)
    if not manifest_path.exists():
        print(f"  ✗ Manifest not found: {manifest_path}")
        sys.exit(1)

    manifest = load_json(manifest_path)
    if not manifest:
        print("  Manifest is empty")
        return

    nodes = load_json(NODES_PATH)
    edges = load_json(EDGES_PATH)

    backup()

    applied = 0
    skipped = 0
    for i, record in enumerate(manifest):
        src_entry_ids = set(record["source_entry_ids"])
        tgt_entry_ids = set(record["target_entry_ids"])

        src_node = find_node_by_entry_id(nodes, src_entry_ids)
        tgt_node = find_node_by_entry_id(nodes, tgt_entry_ids)

        if not src_node and not tgt_node:
            print(f"  [{i+1}] ✗ Neither source nor target found — skip")
            skipped += 1
            continue
        if not src_node:
            print(f"  [{i+1}] ✗ Source not found (entry_ids: {src_entry_ids}) — skip")
            skipped += 1
            continue
        if not tgt_node:
            print(f"  [{i+1}] ✗ Target not found (entry_ids: {tgt_entry_ids}) — skip")
            skipped += 1
            continue
        if src_node["id"] == tgt_node["id"]:
            print(f"  [{i+1}] → Already merged (source==target id={src_node['id']}) — skip")
            skipped += 1
            continue

        print(f"  [{i+1}] Merging id={src_node['id']} → id={tgt_node['id']} ({record.get('reason','')})")
        merge_persons(nodes, edges, src_node["id"], tgt_node["id"])
        applied += 1

    dump_json(nodes, NODES_PATH)
    dump_json(edges, EDGES_PATH)
    print(f"\n  Done: {applied} applied, {skipped} skipped")
    print(f"  Nodes: {len(nodes)}, Edges: {len(edges)}")


def cmd_list(args):
    if not MANIFEST_PATH.exists():
        print("No merges recorded yet.")
        return
    manifest = load_json(MANIFEST_PATH)
    if not manifest:
        print("Manifest is empty.")
        return
    print(f"Recorded merges ({len(manifest)}):\n")
    for i, rec in enumerate(manifest):
        print(f"  [{i+1}] id={rec['source_id']} → id={rec['target_id']}")
        print(f"        {rec.get('source_label','?')} → {rec.get('target_label','?')}")
        print(f"        Reason: {rec.get('reason','')}")
        print()


def cmd_undo(args):
    cmd_list(args)
    if not MANIFEST_PATH.exists():
        return

    manifest = load_json(MANIFEST_PATH)
    if not manifest:
        return

    try:
        idx = int(input("Enter number to undo (0 to cancel): ")) - 1
    except (ValueError, EOFError):
        print("Canceled")
        return

    if idx < 0 or idx >= len(manifest):
        print("Canceled")
        return

    record = manifest[idx]
    print(f"  To undo: id={record['source_id']} → id={record['target_id']}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = sorted(BACKUP_DIR.iterdir())
    if backups:
        print("  Available backups:")
        for b in backups:
            print(f"    {b.name}")
        ans = input("  Enter backup timestamp to restore from (or empty to cancel): ").strip()
        if ans:
            for fname in ("all-nodes.json", "all-edges.json"):
                backup_file = BACKUP_DIR / f"{ans}_{fname}"
                if backup_file.exists():
                    shutil.copy2(backup_file, BASE_DIR / fname)
                    print(f"  Restored {fname}")
            # Remove this record from manifest
            manifest.pop(idx)
            dump_json(manifest, MANIFEST_PATH)
            print(f"  ✓ Undone and removed from manifest")
        else:
            print("  Canceled")
    else:
        print("  No backups found, cannot undo automatically")
        print("  Restore from git or re-run parse.py")


# ── main ────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "merge": cmd_merge,
        "apply": cmd_apply,
        "list": cmd_list,
        "undo": cmd_undo,
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

    commands[command](args)


if __name__ == "__main__":
    main()
