#!/usr/bin/env python3
import json, random, time, urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent
LINKS_FILE = BASE_DIR / "links.md"

NAV_TIMEOUT = 30000
API_TIMEOUT = 15000


def parse_links() -> list[dict]:
    links = []
    for line in LINKS_FILE.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = urllib.parse.urlparse(line)
        qs = urllib.parse.parse_qs(parsed.query)
        uuid = parsed.path.split("/")[-1]
        from_page = int(qs.get("sheet_page_from", [0])[0])
        to_page = int(qs.get("sheet_page_to", [0])[0])
        links.append({"uuid": uuid, "from": from_page, "to": to_page})
    return links


def _extract_archive_meta(breadcrumbs: list[dict]) -> dict:
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


def _ensure_meta(out_dir: Path, page) -> dict | None:
    meta_path = out_dir / "_meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    try:
        pd = page.evaluate("""() => {
            const s = JSON.parse(document.getElementById('__NEXT_DATA__').textContent);
            return s.props.pageProps.breadcrumbs || [];
        }""")
    except Exception:
        return None
    meta = _extract_archive_meta(pd)
    if any(v for v in meta.values()):
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    _meta.json: {meta}")
        return meta
    return None


def download_link(browser, link: dict) -> None:
    uuid = link["uuid"]
    from_page = link["from"]
    to_page = link["to"]
    total = to_page - from_page + 1

    out_dir = BASE_DIR / "raw_api" / uuid
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  {uuid[:8]}.. pages {from_page}-{to_page} ({total} pgs)")

    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        locale="ru-RU",
        viewport={"width": 1280, "height": 720},
    )
    page = context.new_page()

    meta_path = out_dir / "_meta.json"
    if not meta_path.exists():
        # visit first page just to extract archive metadata from breadcrumbs
        first_url = f"https://yandex.ru/archive/catalog/{uuid}/{from_page}"
        try:
            page.goto(first_url, wait_until="load", timeout=NAV_TIMEOUT)
            _ensure_meta(out_dir, page)
        except Exception:
            pass

    for pn in range(from_page, to_page + 1):
        fpath = out_dir / f"page_{pn}.json"
        if fpath.exists():
            print(f"    pg {pn}... cached")
            continue

        print(f"    pg {pn}...", end=" ", flush=True)

        url = f"https://yandex.ru/archive/catalog/{uuid}/{pn}"
        try:
            page.goto(url, wait_until="load", timeout=NAV_TIMEOUT)
        except Exception:
            print("nav∅")
            time.sleep(random.uniform(4.0, 6.0))
            continue

        time.sleep(random.uniform(2.0, 3.0))

        try:
            pd = page.evaluate("""() => {
                const s = JSON.parse(document.getElementById('__NEXT_DATA__').textContent);
                return {
                    nodeId: s.props.pageProps.currentNode.id,
                    hasMarkup: s.props.pageProps.currentNode.hasStructuredMarkup === true,
                };
            }""")
            if not meta_path.exists():
                _ensure_meta(out_dir, page)
        except Exception:
            print("∅")
            time.sleep(random.uniform(4.0, 6.0))
            continue

        if not pd["hasMarkup"]:
            print("∅")
            time.sleep(random.uniform(4.0, 6.0))
            continue

        try:
            resp = page.request.get(
                f"https://yandex.ru/archive/api/structuredMarkup?id={pd['nodeId']}",
                timeout=API_TIMEOUT,
                headers={"Accept": "application/json"},
            )
            api_data = resp.json()
        except Exception:
            print("api∅")
            time.sleep(random.uniform(4.0, 6.0))
            continue

        year = None
        try:
            year = page.evaluate("""() => {
                const s = JSON.parse(document.getElementById('__NEXT_DATA__').textContent);
                const crumbs = s?.props?.pageProps?.breadcrumbs || [];
                for (const bc of crumbs) {
                    if (bc.type === 'File' && bc.dateFrom) {
                        const m = bc.dateFrom.match(/(\\d{4})$/);
                        if (m) return parseInt(m[1]);
                    }
                }
                return null;
            }""")
        except Exception:
            pass

        payload = {
            "year": year,
            "page": pn,
            "node_id": pd['nodeId'],
            "has_markup": True,
            "entries": api_data.get("entries", []),
        }
        fpath.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        entries = len(api_data.get("entries", []))
        print(f"{entries}e")

        time.sleep(random.uniform(4.0, 8.0))

    context.close()


def main():
    print("=" * 60)
    print("Yandex Archive Raw Downloader")
    print("=" * 60)

    links = parse_links()
    print(f"\n{len(links)} links:")
    for l in links:
        print(f"  {l['uuid']}: {l['from']}-{l['to']} ({l['to']-l['from']+1}p)")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for link in links:
                download_link(browser, link)
        finally:
            browser.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
