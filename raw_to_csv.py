#!/usr/bin/env python3
"""Convert raw_api BIRTH entries to CSV with genealogy fields.

Reuses existing parsing modules (parsing/*, reader.py) without modification.
Dates (birth/baptism) are NOT available in the structured JSON — they are in the
page OCR text which is not scraped. Clergy info (priest/deacon/psalomshchik) is
searched across page entries. Parish name is typically on the first (title) page
which has no structured markup and is not scraped.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from parsing.context import _scan_settlements, resolve_context_settlement
from parsing.extract import read_page_file
from parsing.landowner import extract_landowner
from reader import normalize_settlement

BASE_DIR = Path(__file__).parent.resolve()
RAW_API_DIR = BASE_DIR / "raw_api"
DEFAULT_OUTPUT = BASE_DIR / "births.csv"

CSV_FIELDS = [
    "Дата рождения",
    "Дата крещения",
    "Имя родившегося",
    "Имя отца",
    "Имя матери",
    "Сословие отца",
    "Сословие матери",
    "Место проживания отца",
    "Место проживания матери",
    "Имя помещика",
    "Имя восприемника",
    "Имя восприемницы",
    "Сословие восприемника",
    "Сословие восприемницы",
    "Место проживания восприемника",
    "Место проживания восприемницы",
    "ФИО священника проводившего обряд",
    "ФИО диакона",
    "ФИО псаломщика",
    "_год",
    "_страница",
    "_источник",
]

CLERGY_PATTERNS: dict[str, re.Pattern] = {
    "священник": re.compile(
        r"\bсвященник[ау]?\b", re.IGNORECASE
    ),
    "диакон": re.compile(
        r"\bдиакон[ау]?\b", re.IGNORECASE
    ),
    "псаломщик": re.compile(
        r"\bпсаломщик[ау]?\b", re.IGNORECASE
    ),
}

CLERGY_EXCLUDE = re.compile(
    r"\b(дочь|сын[а]?|жена|вдова)\b", re.IGNORECASE
)
LANDOWNER_RE = re.compile(
    r"(?:помещиц[аы]|помещика)\s+\S+(?:\s+\S+)?", re.IGNORECASE
)


def make_full_name(name: str, patronymic: str | None, surname: str | None) -> str:
    parts = [name]
    if patronymic:
        parts.append(patronymic)
    if surname:
        parts.append(surname)
    return " ".join(parts)


def extract_soslovie(info: str) -> str:
    if not info:
        return ""
    cleaned = LANDOWNER_RE.sub("", info)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"^\s*,\s*", "", cleaned)
    cleaned = re.sub(r"\s*,\s*$", "", cleaned)
    return cleaned


def is_clergy(info: str) -> str | None:
    """Return the clergy role if info contains one, excluding relatives."""
    if not info:
        return None
    if CLERGY_EXCLUDE.search(info):
        return None
    for role, pattern in CLERGY_PATTERNS.items():
        if pattern.search(info):
            return role
    return None


_PARTICIPANT_STATUSES = frozenset({"FATHER", "MOTHER", "BORN", "GROOM", "BRIDE"})


def collect_page_clergy(entries: list[dict]) -> dict[str, list[str]]:
    """Collect clergy names from all entries on a page.

    Excludes FATHER/MOTHER/BORN/GROOM/BRIDE status — those are ceremony
    participants, not officiants.  GODFATHER/GODMOTHER are kept because a
    clergyman can be a godparent *and* the officiant at the same ceremony;
    WITNESS/OTHER are often the officiant or his colleague.
    """
    clergy: dict[str, list[str]] = {"священник": [], "диакон": [], "псаломщик": []}
    for entry in entries:
        for ppl in entry.get("people", []):
            status = ppl.get("status", "")
            if status in _PARTICIPANT_STATUSES:
                continue
            role = is_clergy(ppl.get("info", ""))
            if role:
                name = make_full_name(
                    ppl.get("name", ""),
                    ppl.get("second_name") or None,
                    ppl.get("surname") or None,
                )
                if name and name not in clergy[role]:
                    clergy[role].append(name)
    return clergy


def collect_entry_clergy(
    people: list[dict],
) -> dict[str, str]:
    """Collect clergy officiant from 'OTHER' people in the same entry.

    Only 'OTHER' status is considered because the officiant (priest, deacon,
    psalomshchik who performed the rite) is normally listed that way —
    FATHER / GODFATHER / WITNESS clergy people are acting in a different role.
    """
    result: dict[str, str] = {}
    for ppl in people:
        status = ppl.get("status", "")
        if status != "OTHER":
            continue
        role = is_clergy(ppl.get("info", ""))
        if role and role not in result:
            name = make_full_name(
                ppl.get("name", ""),
                ppl.get("second_name") or None,
                ppl.get("surname") or None,
            )
            if name:
                result[role] = name
        if len(result) == 3:
            break
    return result


def _first_settlement(items: list[dict]) -> str | None:
    for item in items:
        s = item.get("settlement")
        if s:
            return s
    return None


def _join_names(items: list[dict]) -> str:
    return "; ".join([p["full_name"] for p in items])


def _join_soslovies(items: list[dict]) -> str:
    seen = []
    result = []
    for p in items:
        s = p.get("soslovie", "")
        if s and s not in seen:
            result.append(s)
            seen.append(s)
    return "; ".join(result)


def _join_settlements(items: list[dict]) -> str:
    seen = []
    result = []
    for p in items:
        s = p.get("settlement") or ""
        if s and s not in seen:
            result.append(s)
            seen.append(s)
    return "; ".join(result)


def process_birth_entries(
    raw_dir: Path = RAW_API_DIR,
) -> list[dict]:
    rows: list[dict] = []

    raw_dirs = sorted(raw_dir.iterdir()) if raw_dir.exists() else []
    if not raw_dirs:
        print(f"No data found in {raw_dir}. Run scraper.py first.", file=sys.stderr)
        return rows

    for uuid_dir in raw_dirs:
        if not uuid_dir.is_dir():
            continue
        uuid = uuid_dir.name
        page_files = sorted(uuid_dir.glob("page_*.json"))
        if not page_files:
            continue

        print(f"\n{uuid[:12]}.. ({len(page_files)} files)", file=sys.stderr)

        for fpath in page_files:
            try:
                year, entries = read_page_file(fpath)
            except (json.JSONDecodeError, OSError, ValueError, KeyError) as exc:
                print(f"  SKIP {fpath}: {exc}", file=sys.stderr)
                continue
            if not entries:
                continue

            m = re.search(r"page_(\d+)", fpath.stem)
            page_num = int(m.group(1)) if m else 0
            page_clergy = collect_page_clergy(entries)

            global_ctx = {
                "uyezd": None,
                "selo": None,
                "selsco": None,
                "derevnya": None,
                "settlement": None,
            }

            for entry in entries:
                if entry.get("type") != "BIRTH":
                    continue

                people = entry.get("people", [])
                if not people:
                    continue

                entry_id = entry.get("entry_id", "")
                archive_url = (
                    f"https://yandex.ru/archive/catalog/{uuid}/{page_num}"
                    f"?entry_id={entry_id}&tab=structured"
                )

                # --- chained landowner extraction (same as parse.py) ---
                raw_settlements: list[str | None] = [
                    p.get("geo") or None for p in people
                ]
                last_landowner: str | None = None
                people_by_status: dict[str, list[dict]] = defaultdict(list)

                for idx, ppl in enumerate(people):
                    status = ppl.get("status", "")
                    name = ppl.get("name", "")
                    patronymic = ppl.get("second_name") or None
                    settlement = ppl.get("geo") or None
                    info = ppl.get("info", "")
                    surname = ppl.get("surname") or None

                    landowner = extract_landowner(info)
                    if landowner:
                        last_landowner = landowner
                    elif "той же помещиц" in info.lower() or "того же помещик" in info.lower():
                        landowner = last_landowner

                    settlement = resolve_context_settlement(
                        settlement, raw_settlements[:idx], global_ctx
                    )
                    if settlement:
                        settlement = normalize_settlement(settlement)

                    soslovie = extract_soslovie(info)
                    full_name = make_full_name(name, patronymic, surname)

                    person = {
                        "name": name,
                        "patronymic": patronymic,
                        "surname": surname,
                        "full_name": full_name,
                        "settlement": settlement,
                        "landowner": landowner,
                        "soslovie": soslovie,
                        "info": info,
                    }
                    people_by_status[status].append(person)

                    if settlement:
                        global_ctx["settlement"] = settlement
                        if re.search(r"\bсело\b", settlement):
                            global_ctx["selo"] = settlement
                        elif re.search(r"\bсельцо\b", settlement):
                            global_ctx["selsco"] = settlement
                        elif re.search(r"\bдеревн[яи]\b", settlement):
                            global_ctx["derevnya"] = settlement
                        m_uy = re.search(
                            r"([^,]+(?:ский|цкий)?\s+уезд)", settlement
                        )
                        if m_uy:
                            global_ctx["uyezd"] = m_uy.group(1)

                # --- settlement fallback: father → mother/born ---
                father_s = _first_settlement(people_by_status.get("FATHER", []))
                born_s = _first_settlement(people_by_status.get("BORN", []))

                for person in people_by_status.get("MOTHER", []):
                    if not person.get("settlement"):
                        person["settlement"] = father_s or born_s
                for person in people_by_status.get("FATHER", []):
                    if not person.get("settlement"):
                        person["settlement"] = born_s
                for person in people_by_status.get("BORN", []):
                    if not person.get("settlement"):
                        person["settlement"] = father_s

                # --- resolve "то же" references with full entry context ---
                all_people = [p for lst in people_by_status.values() for p in lst]
                actual_settlements = [
                    p["settlement"]
                    for p in all_people
                    if p["settlement"]
                    and not any(
                        x in p["settlement"].lower()
                        for x in ("то же", "тот же", "та же", "той же")
                    )
                ]
                if actual_settlements:
                    full_ctx = _scan_settlements(actual_settlements)
                    for person in all_people:
                        s = person.get("settlement")
                        if not s:
                            continue
                        s_lower = s.strip().lower()
                        if any(
                            x in s_lower
                            for x in ("то же", "тот же", "та же", "той же")
                        ):
                            from parsing.context import _resolve_context_ref
                            resolved = _resolve_context_ref(s_lower, full_ctx, global_ctx)
                            if resolved:
                                person["settlement"] = normalize_settlement(resolved)

                # --- clergy: entry-level first, then page-level fallback ---
                entry_clergy = collect_entry_clergy(people)
                priest = entry_clergy.get("священник") or "; ".join(
                    page_clergy.get("священник", [])
                )
                deacon = entry_clergy.get("диакон") or "; ".join(
                    page_clergy.get("диакон", [])
                )
                psalom = entry_clergy.get("псаломщик") or "; ".join(
                    page_clergy.get("псаломщик", [])
                )

                # --- landowner: use first father's landowner if available ---
                fathers = people_by_status.get("FATHER", [])
                landowner = fathers[0].get("landowner") if fathers else ""

                row = {
                    "Дата рождения": "",
                    "Дата крещения": "",
                    "Имя родившегося":
                        _join_names(people_by_status.get("BORN", [])),
                    "Имя отца":
                        _join_names(people_by_status.get("FATHER", [])),
                    "Имя матери":
                        _join_names(people_by_status.get("MOTHER", [])),
                    "Сословие отца":
                        _join_soslovies(people_by_status.get("FATHER", [])),
                    "Сословие матери":
                        _join_soslovies(people_by_status.get("MOTHER", [])),
                    "Место проживания отца":
                        _join_settlements(people_by_status.get("FATHER", [])),
                    "Место проживания матери":
                        _join_settlements(people_by_status.get("MOTHER", [])),
                    "Имя помещика": landowner,
                    "Имя восприемника":
                        _join_names(people_by_status.get("GODFATHER", [])),
                    "Имя восприемницы":
                        _join_names(people_by_status.get("GODMOTHER", [])),
                    "Сословие восприемника":
                        _join_soslovies(people_by_status.get("GODFATHER", [])),
                    "Сословие восприемницы":
                        _join_soslovies(people_by_status.get("GODMOTHER", [])),
                    "Место проживания восприемника":
                        _join_settlements(people_by_status.get("GODFATHER", [])),
                    "Место проживания восприемницы":
                        _join_settlements(people_by_status.get("GODMOTHER", [])),
                    "ФИО священника проводившего обряд": priest,
                    "ФИО диакона": deacon,
                    "ФИО псаломщика": psalom,
                    "_год": year,
                    "_страница": page_num,
                    "_источник": archive_url,
                }
                rows.append(row)

            n_birth = len(
                [
                    e
                    for e in entries
                    if e.get("type") == "BIRTH"
                ]
            )
            print(
                f"  pg {page_num}: {n_birth} births",
                file=sys.stderr,
            )

    return rows


def write_csv(rows: list[dict], output: Path) -> None:
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} rows to {output}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert raw_api BIRTH entries to CSV"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=RAW_API_DIR,
        help="Directory with raw API JSON files (default: raw_api/)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output CSV file path (default: births.csv)",
    )
    args = parser.parse_args()

    print("=" * 60, file=sys.stderr)
    print("raw_api BIRTH → CSV", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    rows = process_birth_entries(args.input_dir)
    if rows:
        write_csv(rows, args.output)
    else:
        print("No BIRTH entries found.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
