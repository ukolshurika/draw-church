#!/usr/bin/env python3
import json
import random
import time
import urllib.parse
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, Browser, sync_playwright


BASE_DIR = Path(__file__).parent.resolve()
LINKS_FILE = BASE_DIR / "links.md"
RAW_API_DIR = BASE_DIR / "raw_api"

NAV_TIMEOUT = 30000
API_TIMEOUT = 15000

DELAYS = {
    "after_nav": (2.0, 3.0),
    "after_err": (4.0, 6.0),
    "after_api": (4.0, 8.0),
}

RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 2.0

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Safari/537.36"
)


def _jitter(lo: float, hi: float) -> float:
    return random.uniform(lo, hi)


# ── Models ──

@dataclass
class Link:
    uuid: str
    from_page: int = 1
    to_page: int | None = None

    @property
    def total_pages(self) -> int | None:
        if self.to_page is None:
            return None
        return self.to_page - self.from_page + 1


@dataclass
class ArchiveMeta:
    archive: str | None = None
    fund: str | None = None
    opis: str | None = None
    delo: str | None = None
    total_pages: int | None = None

    def is_populated(self) -> bool:
        return any(getattr(self, f.name) for f in fields(self) if f.name != "total_pages")

    def to_dict(self) -> dict[str, str | None]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class RawPageData:
    node_id: int
    has_markup: bool
    year: int | None
    breadcrumbs: list[dict]
    total_pages: int | None = None


@dataclass
class PageData:
    year: int | None
    page: int
    node_id: int
    has_markup: bool
    entries: list
    total_pages: int | None = None


# ── Services: Link Parsing ──

class LinkParser:
    @staticmethod
    def parse() -> list[Link]:
        links: list[Link] = []
        for line in LINKS_FILE.read_text(encoding="utf-8").strip().splitlines():
            link = LinkParser._parse_line(line)
            if link:
                links.append(link)
        return links

    @staticmethod
    def _parse_line(line: str) -> Link | None:
        line = line.strip()
        if not line or line.startswith("#"):
            return None

        parsed = urllib.parse.urlparse(line)
        if not parsed.scheme or not parsed.netloc:
            print(f"  skip invalid url: {line}")
            return None

        qs = urllib.parse.parse_qs(parsed.query)
        uuid = parsed.path.split("/")[-1]
        if not uuid or len(uuid) < 8:
            print(f"  skip: bad uuid {uuid!r} from {line}")
            return None

        try:
            from_page = int(qs.get("sheet_page_from", [1])[0])
        except (ValueError, IndexError) as e:
            print(f"  skip: bad sheet_page_from in {line}: {e}")
            return None

        to_page: int | None
        try:
            to_page = int(qs.get("sheet_page_to", [""])[0])
        except (ValueError, IndexError):
            to_page = None

        if from_page < 1:
            print(f"  skip: invalid from_page {from_page} in {line}")
            return None

        if to_page is not None and to_page < from_page:
            print(f"  skip: invalid range {from_page}-{to_page} in {line}")
            return None

        return Link(uuid=uuid, from_page=from_page, to_page=to_page)


# ── Services: Yandex API ──

class YandexApiClient:
    def fetch_structured_markup(self, page: Page, node_id: int) -> dict[str, Any] | None:
        url = f"https://yandex.ru/archive/api/structuredMarkup?id={node_id}"
        for attempt in range(RETRY_ATTEMPTS):
            try:
                result = page.evaluate(f"""() => {{
                    return fetch('{url}')
                        .then(r => {{
                            if (!r.ok) throw new Error('HTTP ' + r.status);
                            return r.json();
                        }});
                }}""")
                return result
            except Exception as e:
                print(f"api fail (attempt {attempt+1}): {e}", end="")
                if attempt < RETRY_ATTEMPTS - 1:
                    delay = _jitter(0.5, 1.0) * (RETRY_BACKOFF**attempt)
                    print(f" retry in {delay:.1f}s")
                    time.sleep(delay)
                else:
                    print()
        return None


# ── Services: Page Data Extraction ──

class MetadataExtractor:
    @staticmethod
    def from_page(page: Page) -> ArchiveMeta | None:
        breadcrumbs = MetadataExtractor._extract_breadcrumbs(page)
        if breadcrumbs is None:
            return None
        return MetadataExtractor.from_breadcrumbs(breadcrumbs)

    @staticmethod
    def from_breadcrumbs(breadcrumbs: list[dict]) -> ArchiveMeta:
        meta = ArchiveMeta()
        for b in breadcrumbs:
            t = b.get("type", "")
            if t == "Archive":
                meta.archive = b.get("name", "")
            elif t == "Fund":
                meta.fund = b.get("code", "")
            elif t == "Inventory":
                meta.opis = b.get("code", "")
            elif t == "File":
                meta.delo = b.get("code", "")
        return meta

    @staticmethod
    def _extract_breadcrumbs(page: Page) -> list[dict] | None:
        try:
            return page.evaluate("""() => {
                const el = document.getElementById('__NEXT_DATA__');
                if (!el) return null;
                const s = JSON.parse(el.textContent);
                return s.props.pageProps.breadcrumbs || [];
            }""")
        except Exception as e:
            print(f"    meta extract failed: {e}")
            return None


class PageDataExtractor:
    @staticmethod
    def from_page(page: Page) -> RawPageData | None:
        try:
            result = page.evaluate("""() => {
                const el = document.getElementById('__NEXT_DATA__');
                if (!el) return null;
                const s = JSON.parse(el.textContent);
                const pp = s.props.pageProps;
                const cn = pp.currentNode || {};
                const crumbs = pp.breadcrumbs || [];

                let year = null;
                for (const bc of crumbs) {
                    if (bc.type === 'File' && bc.dateFrom) {
                        const m = bc.dateFrom.match(/(\\d{4})/);
                        if (m) { year = parseInt(m[1]); break; }
                    }
                }

                return {
                    nodeId: cn.id,
                    hasMarkup: cn.hasStructuredMarkup === true,
                    year: year,
                    breadcrumbs: crumbs,
                    totalPages: pp.totalPages || null,
                };
            }""")
        except Exception as e:
            print(f"    page data extract failed: {e}")
            return None

        if result is None:
            return None

        return RawPageData(
            node_id=result["nodeId"],
            has_markup=result["hasMarkup"],
            year=result["year"],
            breadcrumbs=result["breadcrumbs"],
            total_pages=result["totalPages"],
        )


# ── Services: File I/O ──

class FileStorage:
    def __init__(self, base_dir: Path = RAW_API_DIR) -> None:
        self.base_dir = base_dir

    def _link_dir(self, uuid: str) -> Path:
        return self.base_dir / uuid

    def _meta_path(self, uuid: str) -> Path:
        return self._link_dir(uuid) / "_meta.json"

    def _page_path(self, uuid: str, page: int) -> Path:
        return self._link_dir(uuid) / f"page_{page}.json"

    def read_meta(self, uuid: str) -> ArchiveMeta | None:
        path = self._meta_path(uuid)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ArchiveMeta(**data)

    def write_meta(self, uuid: str, meta: ArchiveMeta) -> None:
        self._link_dir(uuid).mkdir(parents=True, exist_ok=True)
        self._meta_path(uuid).write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_page_cached(self, uuid: str, page: int) -> bool:
        return self._page_path(uuid, page).exists()

    def read_page(self, uuid: str, page: int) -> dict | None:
        path = self._page_path(uuid, page)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_page(self, uuid: str, page_num: int, data: PageData) -> None:
        self._link_dir(uuid).mkdir(parents=True, exist_ok=True)
        self._page_path(uuid, page_num).write_text(
            json.dumps({
                "year": data.year,
                "page": data.page,
                "node_id": data.node_id,
                "has_markup": data.has_markup,
                "entries": data.entries,
                "total_pages": data.total_pages,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ── Services: Browser Session ──

class BrowserSession:
    def __init__(self, browser: Browser) -> None:
        self._browser = browser
        self._page: Page | None = None
        self._context = None

    def __enter__(self) -> "BrowserSession":
        self._context = self._browser.new_context(
            user_agent=USER_AGENT,
            locale="ru-RU",
            viewport={"width": 1280, "height": 720},
        )
        self._page = self._context.new_page()
        return self

    def __exit__(self, *args) -> None:
        if self._context:
            self._context.close()
        self._page = None

    @property
    def page(self) -> Page:
        assert self._page is not None
        return self._page

    def navigate(self, url: str) -> bool:
        try:
            self.page.goto(url, wait_until="load", timeout=NAV_TIMEOUT)
            return True
        except Exception as e:
            print(f"    nav failed: {e}")
            return False


# ── Orchestration: Per-Link Downloader ──

class LinkDownloader:
    def __init__(
        self,
        browser: Browser,
        api_client: YandexApiClient,
        storage: FileStorage,
    ) -> None:
        self._browser = browser
        self._api_client = api_client
        self._storage = storage

    def download(self, link: Link) -> None:
        uuid = link.uuid

        if link.to_page is not None:
            print(f"\n  {uuid[:8]}.. pages {link.from_page}-{link.to_page} ({link.total_pages} pgs)")
        else:
            print(f"\n  {uuid[:8]}.. pages {link.from_page}-? (auto-discover)")

        meta = self._load_meta(uuid)

        with BrowserSession(self._browser) as session:
            if meta is None:
                meta, total_pages = self._try_extract_first_meta(session, uuid, link.from_page)
                if meta is None and total_pages is None:
                    print(f"    could not load first page, skipping")
                    return
            else:
                total_pages = meta.total_pages if meta else None

            if link.to_page is not None:
                end_page = link.to_page
            elif total_pages is not None:
                end_page = total_pages
            else:
                total_pages = self._discover_total_pages(session, uuid, link.from_page)
                if total_pages is None:
                    print(f"    could not discover total pages, skipping")
                    return
                end_page = total_pages
                if meta:
                    meta.total_pages = total_pages
                    self._storage.write_meta(uuid, meta)
                print(f"    auto-discovered {end_page} total pages")

            for pn in range(link.from_page, end_page + 1):
                self._download_page(session, uuid, pn, meta)

    def _load_meta(self, uuid: str) -> ArchiveMeta | None:
        meta = self._storage.read_meta(uuid)
        if meta:
            return meta
        return None

    def _try_extract_first_meta(self, session: BrowserSession, uuid: str, first_page: int) -> tuple[ArchiveMeta | None, int | None]:
        url = f"https://yandex.ru/archive/catalog/{uuid}/{first_page}"
        if not session.navigate(url):
            return None, None

        raw = PageDataExtractor.from_page(session.page)
        meta = None
        total_pages = None
        if raw:
            meta = MetadataExtractor.from_breadcrumbs(raw.breadcrumbs)
            total_pages = raw.total_pages
            if meta:
                meta.total_pages = total_pages
                if meta.is_populated():
                    self._storage.write_meta(uuid, meta)
                    print(f"    _meta.json: {meta}")
            return meta, total_pages
        else:
            meta = MetadataExtractor.from_page(session.page)
            if meta:
                if meta.is_populated():
                    self._storage.write_meta(uuid, meta)
                    print(f"    _meta.json: {meta}")
            return meta, None

    def _discover_total_pages(self, session: BrowserSession, uuid: str, page_num: int) -> int | None:
        if self._storage.is_page_cached(uuid, page_num):
            cached = self._storage.read_page(uuid, page_num)
            if cached and cached.get("total_pages"):
                return cached["total_pages"]

        url = f"https://yandex.ru/archive/catalog/{uuid}/{page_num}"
        if not session.navigate(url):
            return None

        raw = PageDataExtractor.from_page(session.page)
        if raw is None:
            return None

        return raw.total_pages

    def _download_page(
        self,
        session: BrowserSession,
        uuid: str,
        pn: int,
        meta: ArchiveMeta | None,
    ) -> ArchiveMeta | None:
        if self._storage.is_page_cached(uuid, pn):
            print(f"    pg {pn}... cached")
            return meta

        print(f"    pg {pn}...", end=" ", flush=True)

        url = f"https://yandex.ru/archive/catalog/{uuid}/{pn}"
        if not session.navigate(url):
            time.sleep(_jitter(*DELAYS["after_err"]))
            return meta

        time.sleep(_jitter(*DELAYS["after_nav"]))

        raw = PageDataExtractor.from_page(session.page)
        if raw is None:
            time.sleep(_jitter(*DELAYS["after_err"]))
            return meta

        if meta is None or not meta.is_populated():
            extracted = MetadataExtractor.from_breadcrumbs(raw.breadcrumbs)
            if extracted.is_populated():
                self._storage.write_meta(uuid, extracted)
                print(f"    _meta.json: {extracted}")
                meta = extracted

        if not raw.has_markup:
            print("∅")
            time.sleep(_jitter(*DELAYS["after_err"]))
            return meta

        api_data = self._api_client.fetch_structured_markup(session.page, raw.node_id)
        if api_data is None:
            time.sleep(_jitter(*DELAYS["after_err"]))
            return meta

        page_data = PageData(
            year=raw.year,
            page=pn,
            node_id=raw.node_id,
            has_markup=raw.has_markup,
            entries=api_data.get("entries", []),
        )
        self._storage.write_page(uuid, pn, page_data)

        entries = len(page_data.entries)
        print(f"{entries}e")

        time.sleep(_jitter(*DELAYS["after_api"]))

        return meta


# ── Orchestration: Main ──

class DownloadOrchestrator:
    def run(self, output_dir: Path | None = None) -> None:
        print("=" * 60)
        print("Yandex Archive Raw Downloader")
        print("=" * 60)

        links = LinkParser.parse()
        if not links:
            print("\nNo valid links found. Check links.md")
            return

        print(f"\n{len(links)} links:")
        for l in links:
            if l.to_page is not None:
                print(f"  {l.uuid}: {l.from_page}-{l.to_page} ({l.total_pages}p)")
            else:
                print(f"  {l.uuid}: {l.from_page}-? (auto-discover)")

        api_client = YandexApiClient()
        storage = FileStorage(output_dir or RAW_API_DIR)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for link in links:
                    downloader = LinkDownloader(browser, api_client, storage)
                    downloader.download(link)
            finally:
                browser.close()

        print("\nDone.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Download raw API data from Yandex Archive")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Output directory for raw API data (default: raw_api/)")
    args = parser.parse_args()
    DownloadOrchestrator().run(output_dir=args.output_dir)


if __name__ == "__main__":
    main()
