import json, re
from itertools import count
from pathlib import Path

from reader import normalize_settlement

from .models import (
    STATUS_TO_RELATION,
    WEDDING_STATUS_TO_RELATION,
    _UYEZD_RE,
    RAW_API_DIR,
)
from .landowner import extract_landowner
from .context import resolve_context_settlement


def build_edges(entry_type: str, people_by_status: dict[str, list[int]]) -> list[dict]:
    edges = []
    if entry_type == "BIRTH":
        born = people_by_status.get("BORN", [])
        parents = people_by_status.get("MOTHER", []) + people_by_status.get("FATHER", [])
        for b in born:
            for p in parents:
                edges.append({"source_id": b, "target_id": p, "relation": "child_of"})
        mothers = people_by_status.get("MOTHER", [])
        fathers = people_by_status.get("FATHER", [])
        if len(fathers) == 1 and len(mothers) == 1:
            edges.append({"source_id": fathers[0], "target_id": mothers[0], "relation": "married_to"})
        gp = people_by_status.get("GODFATHER", []) + people_by_status.get("GODMOTHER", [])
        for g in gp:
            for b in born:
                edges.append({"source_id": g, "target_id": b, "relation": "godparent_of"})
        others = people_by_status.get("OTHER", [])
        for o in others:
            for b in born:
                edges.append({"source_id": o, "target_id": b, "relation": "other"})
    elif entry_type == "WEDDING":
        grooms = people_by_status.get("GROOM", [])
        brides = people_by_status.get("BRIDE", [])
        for g in grooms:
            for b in brides:
                edges.append({"source_id": g, "target_id": b, "relation": "married_to"})
        witnesses = people_by_status.get("WITNESS", [])
        for w in witnesses:
            for g in grooms:
                edges.append({"source_id": w, "target_id": g, "relation": "witnessed_for"})
            for b in brides:
                edges.append({"source_id": w, "target_id": b, "relation": "witnessed_for"})
    return edges


def process_entry(entry: dict, year: int, counter,
                  archive_url: str,
                  archive_meta: dict | None = None,
                  page: int = 0,
                  global_ctx: dict | None = None
) -> tuple[list[dict], list[dict]]:
    entry_type = entry.get("type")
    if entry_type not in ("BIRTH", "WEDDING"):
        return [], []

    if global_ctx is None:
        global_ctx = {"uyezd": None, "selo": None, "selsco": None, "derevnya": None, "settlement": None}

    raw_people = entry.get("people", [])
    persons = []
    people_by_status: dict[str, list[int]] = {}

    raw_settlements: list[str | None] = [p.get("geo") or None for p in raw_people]
    last_landowner: str | None = None

    for idx, ppl in enumerate(raw_people):
        status = ppl.get("status", "")
        name = ppl.get("name", "")
        second_name = ppl.get("second_name") or None
        settlement = ppl.get("geo") or None
        info = ppl.get("info", "")
        surname = ppl.get("surname") or None

        landowner = extract_landowner(info)
        if landowner:
            last_landowner = landowner
        elif "той же помещиц" in info.lower() or "того же помещик" in info.lower():
            landowner = last_landowner

        settlement = resolve_context_settlement(settlement, raw_settlements[:idx], global_ctx)
        if settlement:
            settlement = normalize_settlement(settlement)

        temp_id = next(counter)

        record_type = "Родившийся" if entry_type == "BIRTH" else "Бракосочетание"
        relation_type = (
            STATUS_TO_RELATION.get(status, status)
            if entry_type == "BIRTH"
            else WEDDING_STATUS_TO_RELATION.get(status, status)
        )

        source = {
            "archive": (archive_meta or {}).get("archive"),
            "fund": (archive_meta or {}).get("fund"),
            "opis": (archive_meta or {}).get("opis"),
            "delo": (archive_meta or {}).get("delo"),
            "page": page,
            "url": archive_url,
        }

        persons.append({
            "_temp_id": temp_id,
            "_archive_url": archive_url,
            "_source": source,
            "_raw_status": status,
            "first_name": name,
            "patronymic": second_name,
            "surname": surname,
            "year": year,
            "relation_type": relation_type,
            "record_type": record_type,
            "landowner": landowner,
            "settlement": settlement,
        })

        people_by_status.setdefault(status, []).append(temp_id)

    # Apply settlement fallback for parents/children in BIRTH entries.
    # Hierarchy: father has settlement → mother and born get it.
    #            born has settlement → parents get it.
    # Godparents and OTHER are NOT used as fallback sources.
    if entry_type == "BIRTH":
        father_settlement: str | None = None
        born_settlement: str | None = None
        for person in persons:
            s = person.get("settlement")
            if s:
                raw_status = person.get("_raw_status")
                if raw_status == "FATHER":
                    father_settlement = s
                elif raw_status == "BORN":
                    born_settlement = s

        for person in persons:
            if person.get("settlement") is None:
                raw_status = person.get("_raw_status")
                if raw_status == "MOTHER":
                    person["settlement"] = father_settlement or born_settlement
                elif raw_status == "FATHER":
                    person["settlement"] = born_settlement
                elif raw_status == "BORN":
                    person["settlement"] = father_settlement

    edges = build_edges(entry_type, people_by_status)
    return persons, edges


def load_archive_meta(uuid: str) -> dict | None:
    meta_path = RAW_API_DIR / uuid / "_meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return None


def process_page_data(data: dict, year: int, counter,
                       uuid: str = "", page: int = 0
) -> tuple[list[dict], list[dict]]:
    all_persons = []
    all_edges = []
    archive_meta = load_archive_meta(uuid)
    global_ctx = {"uyezd": None, "selo": None, "selsco": None, "derevnya": None, "settlement": None}
    for entry in data.get("entries", []):
        entry_id = entry.get("entry_id", "")
        archive_url = f"https://yandex.ru/archive/catalog/{uuid}/{page}?entry_id={entry_id}&tab=structured"
        p, e = process_entry(entry, year, counter, archive_url, archive_meta, page, global_ctx)
        all_persons.extend(p)
        all_edges.extend(e)
        for person in p:
            s = person.get("settlement")
            if s:
                global_ctx["settlement"] = s
                if re.search(r"\bсело\b", s):
                    global_ctx["selo"] = s
                elif re.search(r"\bсельцо\b", s):
                    global_ctx["selsco"] = s
                elif re.search(r"\bдеревн[яи]\b", s):
                    global_ctx["derevnya"] = s
                m = _UYEZD_RE.search(s)
                if m:
                    global_ctx["uyezd"] = m.group(1)
    return all_persons, all_edges


def extract_year_from_filename(fpath: Path) -> int | None:
    name = fpath.stem
    m = re.search(r"(\d{4})", name)
    if m:
        return int(m.group(1))
    return None


def read_page_file(fpath: Path) -> tuple[int, list[dict]]:
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"SKIP {fpath}: {exc}")
        return 0, []
    if "year" in data:
        year = data["year"] or 0
    else:
        year = extract_year_from_filename(fpath) or 0
    entries = data.get("entries", [])
    if not entries and "api_response" in data:
        entries = data["api_response"].get("entries", [])
    return year, entries
