#!/usr/bin/env python3
"""Full pipeline: Yandex.Archive links → scraper → births.csv.

1. Writes links to links.md (backing up original if present)
2. Runs scraper.py --output-dir raw_api_{PREFIX}/
3. Runs raw_to_csv.py --input-dir raw_api_{PREFIX}/ --output {PREFIX}_births.csv

Usage:
    python3 create_csv.py PREFIX \\
        "https://yandex.ru/archive/catalog/UUID?sheet_page_from=X&sheet_page_to=Y" \\
        "https://yandex.ru/archive/catalog/UUID2?sheet_page_from=A&sheet_page_to=B"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
LINKS_FILE = BASE_DIR / "links.md"


def run_cmd(cmd: list[str], step_name: str) -> int:
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(f"  {step_name}", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)
    result = subprocess.run(cmd, cwd=BASE_DIR)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Full pipeline: links → scraper → births.csv"
    )
    parser.add_argument(
        "prefix",
        help="Save prefix (e.g. 'moscow_1913'). "
        "Raw data goes to raw_api_{prefix}/, CSV to {prefix}_births.csv.",
    )
    parser.add_argument(
        "urls",
        nargs="+",
        help="Yandex.Archive URLs (one or more)",
    )
    args = parser.parse_args()
    prefix = args.prefix
    raw_dir = BASE_DIR / f"raw_api_{prefix}"
    csv_out = BASE_DIR / f"{prefix}_births.csv"

    print(f"Prefix:   {prefix}", file=sys.stderr)
    print(f"Raw dir:  {raw_dir}", file=sys.stderr)
    print(f"CSV out:  {csv_out}", file=sys.stderr)
    print(f"URLs ({len(args.urls)}):", file=sys.stderr)
    for u in args.urls:
        print(f"  {u}", file=sys.stderr)

    # 1. Backup links.md
    links_backup = None
    if LINKS_FILE.exists():
        links_backup = LINKS_FILE.read_text(encoding="utf-8")
        print(
            f"\nBacked up existing links.md"
            f" ({len(links_backup.splitlines())} lines)",
            file=sys.stderr,
        )

    # 2. Write new links
    LINKS_FILE.write_text("\n".join(args.urls) + "\n", encoding="utf-8")
    print(f"Wrote {len(args.urls)} URLs to links.md", file=sys.stderr)

    # 3. Run scraper
    rc = run_cmd(
        ["python3", "scraper.py", "--output-dir", str(raw_dir)],
        f"Step 1/2: Scraping → {raw_dir}",
    )
    scraper_ok = rc == 0

    # 4. Restore original links.md
    if links_backup is not None:
        LINKS_FILE.write_text(links_backup, encoding="utf-8")
        print("Restored original links.md", file=sys.stderr)
    else:
        LINKS_FILE.unlink(missing_ok=True)

    if not scraper_ok:
        print("\nScraper failed — stopping.", file=sys.stderr)
        sys.exit(1)

    # 5. Run CSV generator
    rc = run_cmd(
        ["python3", "raw_to_csv.py", "--input-dir", str(raw_dir), "--output", str(csv_out)],
        "Step 2/2: Generating CSV",
    )
    if rc != 0:
        print("\nCSV generation failed.", file=sys.stderr)
        sys.exit(1)

    print(f"\nDone! CSV saved to {csv_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
