import argparse
import json
import re
import sys
from itertools import count
from pathlib import Path

from .models import OUTPUT_NODES, OUTPUT_EDGES, RAW_API_DIR
from .extract import process_page_data, read_page_file
from .dedup import deduplicate


def run(input_dir: Path, output_nodes: Path, output_edges: Path,
        dry_run: bool = False):
    """Core logic — callable from code with explicit paths."""
    raw_dirs = sorted(input_dir.iterdir()) if input_dir.exists() else []
    if not raw_dirs:
        print(f"No data found in {input_dir}. Run scraper.py first.")
        return

    all_persons = []
    all_edges = []
    temp_id_counter = count(1)

    for uuid_dir in raw_dirs:
        if not uuid_dir.is_dir():
            continue
        uuid = uuid_dir.name
        page_files = sorted(uuid_dir.glob("page_*.json"))
        if not page_files:
            continue

        print(f"\n{uuid[:12]}.. ({len(page_files)} files)")

        for fpath in page_files:
            try:
                year, entries = read_page_file(fpath)
                if not entries:
                    continue
                m = re.search(r"page_(\d+)", fpath.stem)
                page_num = int(m.group(1)) if m else 0
                data = {"entries": entries}
                persons, edges = process_page_data(data, year, temp_id_counter, uuid, page_num)
                print(f"  pg {page_num}: {len(persons)}p {len(edges)}e")
                all_persons.extend(persons)
                all_edges.extend(edges)
            except Exception as exc:
                print(f"  SKIP {fpath}: {exc}")

    print(f"\n{'='*60}")
    print(f"Raw: {len(all_persons)} persons, {len(all_edges)} edges")

    if not all_persons:
        print("No data extracted.")
        return

    print("Deduplicating...")
    unique_persons, tid_map = deduplicate(all_persons)
    print(f"After dedup: {len(unique_persons)}")

    final_edges = []
    for e in all_edges:
        s = tid_map.get(e["source_id"])
        t = tid_map.get(e["target_id"])
        if s and t:
            final_edges.append({"source_id": s, "target_id": t, "relation": e["relation"]})

    if dry_run:
        print(f"\n[DRY RUN] Would write: {output_nodes.name} ({len(unique_persons)} nodes)")
        print(f"[DRY RUN] Would write: {output_edges.name} ({len(final_edges)} edges)")
    else:
        output_nodes.write_text(
            json.dumps(unique_persons, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        output_edges.write_text(
            json.dumps(final_edges, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nSaved: {output_nodes.name} ({len(unique_persons)} nodes)")
        print(f"Saved: {output_edges.name} ({len(final_edges)} edges)")

    print("Done!")


def main():
    parser = argparse.ArgumentParser(description="Parse raw API → nodes + edges")
    parser.add_argument("--input-dir", type=Path, default=RAW_API_DIR,
                        help="Directory with raw API JSON files")
    parser.add_argument("--output-nodes", type=Path, default=OUTPUT_NODES,
                        help="Output nodes JSON file")
    parser.add_argument("--output-edges", type=Path, default=OUTPUT_EDGES,
                        help="Output edges JSON file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse without writing output files")
    args = parser.parse_args()

    print("=" * 60)
    print("Parse raw API → nodes + edges")
    print("=" * 60)

    run(args.input_dir, args.output_nodes, args.output_edges, args.dry_run)
