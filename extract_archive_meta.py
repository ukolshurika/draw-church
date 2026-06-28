#!/usr/bin/env python3
"""Backfill archive metadata (_meta.json) for existing raw_api UUID directories.

Uses curl + __NEXT_DATA__ from HTML to avoid Playwright dependency.
"""

import json, re, subprocess, sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
RAW_API_DIR = BASE_DIR / "raw_api"

CURL_HEADERS = [
    "-sL", "--max-time", "15",
    "-H", "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
]


def extract_archive_meta(breadcrumbs: list[dict]) -> dict:
    meta: dict[str, str | None] = {"archive": None, "fund": None, "opis": None, "delo": None}
    for b in breadcrumbs:
        t = b.get("type", "")
        if t == "Archive":
            meta["archive"] = b.get("name", "")
        elif t == "Fund":
            meta["fund"] = b.get("code", "")
        elif t == "Inventory":
            meta["opis"] = b.get("code", "")
        elif t == "File":
            meta["delo"] = b.get("code", "")
    return meta


def fetch_breadcrumbs(uuid: str, page: int = 0) -> list[dict] | None:
    url = f"https://yandex.ru/archive/catalog/{uuid}/{page}"
    try:
        html = subprocess.check_output(
            ["curl", *CURL_HEADERS, url], timeout=20
        ).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  curl error: {e}", file=sys.stderr)
        return None

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>({.*?})</script>', html, re.DOTALL)
    if not m:
        print(f"  __NEXT_DATA__ not found", file=sys.stderr)
        return None

    try:
        data = json.loads(m.group(1))
        return data["props"]["pageProps"]["breadcrumbs"]
    except (KeyError, json.JSONDecodeError) as e:
        print(f"  parse error: {e}", file=sys.stderr)
        return None


def main():
    print("=" * 60)
    print("Extract archive metadata (backfill)")
    print("=" * 60)

    uuid_dirs = sorted(RAW_API_DIR.iterdir()) if RAW_API_DIR.exists() else []
    if not uuid_dirs:
        print("No raw_api data found.")
        return

    for uuid_dir in uuid_dirs:
        if not uuid_dir.is_dir():
            continue
        uuid = uuid_dir.name
        meta_path = uuid_dir / "_meta.json"

        if meta_path.exists():
            print(f"  {uuid[:12]}.. _meta.json exists, skipping")
            continue

        # find first page file to determine which page to crawl
        page_files = sorted(uuid_dir.glob("page_*.json"))
        if not page_files:
            print(f"  {uuid[:12]}.. no page files, skipping")
            continue

        first_page = int(re.search(r"page_(\d+)", page_files[0].stem).group(1))
        print(f"  {uuid[:12]}.. fetching page {first_page}...", end=" ", flush=True)

        crumbs = fetch_breadcrumbs(uuid, first_page)
        if not crumbs:
            print("FAILED")
            continue

        meta = extract_archive_meta(crumbs)
        if not any(v for v in meta.values()):
            print("no metadata found")
            continue

        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"OK: {meta}")

    print("\nDone.")


if __name__ == "__main__":
    main()
