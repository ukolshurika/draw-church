#!/usr/bin/env python3
import json, re
from pathlib import Path

from reader import normalize_settlement

BASE_DIR = Path(__file__).parent
RAW_API_DIR = BASE_DIR / "raw_api"
OUTPUT_NODES = BASE_DIR / "all-nodes.json"
OUTPUT_EDGES = BASE_DIR / "all-edges.json"

STATUS_TO_RELATION = {
    "BORN": "Родившийся",
    "MOTHER": "Родитель",
    "FATHER": "Родитель",
    "GODFATHER": "Восприемник",
    "GODMOTHER": "Восприемник",
    "OTHER": "Другой",
}
WEDDING_STATUS_TO_RELATION = {
    "GROOM": "Жених",
    "BRIDE": "Невеста",
    "WITNESS": "Свидетель",
}


def extract_landowner(info_text: str) -> str | None:
    m = re.search(
        r"(?:помещиц[аы]|помещика)\s+(.+?)(?:\s+крестьянин|\s+крестьянка|\s*$)",
        info_text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return None


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
        for m in mothers:
            for f in fathers:
                edges.append({"source_id": f, "target_id": m, "relation": "married_to"})
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


def _scan_settlements(settlements: list[str | None]) -> dict:
    """Scan a list of settlements and return last-known values."""
    ctx = {
        "uyezd": None,
        "selo": None,
        "selsco": None,
        "derevnya": None,
        "settlement": None,
    }
    for s in settlements:
        if s is None:
            continue
        ctx["settlement"] = s
        m = re.match(r"([^,]+(?:ский|цкий)?\s+уезд)", s)
        if m:
            ctx["uyezd"] = m.group(1)
        if re.search(r"\bсело\b", s):
            ctx["selo"] = s
        elif re.search(r"\bсельцо\b", s):
            ctx["selsco"] = s
        elif re.search(r"\bдеревн[яи]\b", s):
            ctx["derevnya"] = s
    return ctx


def _resolve_context_ref(s_lower: str, entry_ctx: dict, global_ctx: dict) -> str | None:
    """Try to resolve a 'та же / тот же' reference using entry then global context."""
    same_prefix = re.match(r"(т[оа]й?\s+же)\s+(.+)", s_lower)
    if not same_prefix:
        # "тот же уезд, деревня X"
        m = re.match(r"тот\s+же\s+уезд,\s*(деревня\s+\S+)", s_lower)
        if m:
            uyezd = entry_ctx["uyezd"] or global_ctx["uyezd"]
            if uyezd:
                return f"{uyezd}, {m.group(1)}"
        return None

    ref_type = same_prefix.group(2).strip()

    # Determine which type of settlement is being referenced
    type_candidates = {
        "деревня": ("derevnya",),
        "село": ("selo",),
        "сельцо": ("selsco",),
        "деревни": ("derevnya",),  # genitive form
        "села": ("selo",),
        "сельца": ("selsco",),
    }
    target_keys = None
    for key, keys in type_candidates.items():
        if ref_type.startswith(key):
            target_keys = keys
            break

    # Try to resolve from entry context first
    if target_keys:
        for k in target_keys:
            val = entry_ctx.get(k)
            if val:
                return val
        # Fall back to global context
        for k in target_keys:
            val = global_ctx.get(k)
            if val:
                return val

    # Type not recognized — try last settlement from entry, then global
    settlement = entry_ctx["settlement"] or global_ctx["settlement"]
    if settlement:
        for part in re.split(r"[,·]", settlement):
            if ref_type in part.lower().strip():
                return part.strip()
    return settlement


def resolve_context_settlement(
    settlement: str | None,
    entry_settlements: list[str | None],
    global_ctx: dict | None = None,
) -> str | None:
    if settlement is None:
        return None

    entry_ctx = _scan_settlements(entry_settlements)
    if global_ctx is None:
        global_ctx = {"uyezd": None, "selo": None, "selsco": None, "derevnya": None, "settlement": None}

    s_lower = settlement.lower().strip()
    resolved = _resolve_context_ref(s_lower, entry_ctx, global_ctx)
    if resolved:
        return resolved

    # "тот же уезд" pattern (full form, not just prefix)
    m = re.match(r"тот\s+же\s+уезд,\s*(деревня\s+\S+)", s_lower)
    if m:
        uyezd = entry_ctx["uyezd"] or global_ctx["uyezd"]
        if uyezd:
            return f"{uyezd}, {m.group(1)}"

    return settlement


def process_entry(entry: dict, year: int, temp_id_counter: list[int],
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
        if settlement is None and entry_type == "BIRTH" and status in ("MOTHER", "FATHER"):
            for prev in reversed(persons):
                s = prev.get("settlement")
                if s:
                    settlement = s
                    break
        if settlement:
            settlement = normalize_settlement(settlement)

        temp_id_counter[0] += 1
        temp_id = temp_id_counter[0]

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

    edges = build_edges(entry_type, people_by_status)
    return persons, edges


def load_archive_meta(uuid: str) -> dict | None:
    meta_path = RAW_API_DIR / uuid / "_meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return None


def process_page_data(data: dict, year: int, temp_id_counter: list[int],
                      uuid: str = "", page: int = 0
) -> tuple[list[dict], list[dict]]:
    all_persons = []
    all_edges = []
    archive_meta = load_archive_meta(uuid)
    global_ctx = {"uyezd": None, "selo": None, "selsco": None, "derevnya": None, "settlement": None}
    for entry in data.get("entries", []):
        entry_id = entry.get("entry_id", "")
        archive_url = f"https://yandex.ru/archive/catalog/{uuid}/{page}?entry_id={entry_id}&tab=structured"
        p, e = process_entry(entry, year, temp_id_counter, archive_url, archive_meta, page, global_ctx)
        all_persons.extend(p)
        all_edges.extend(e)
        # Update global context from this entry's resolved settlements
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
                m = re.match(r"([^,]+(?:ский|цкий)?\s+уезд)", s)
                if m:
                    global_ctx["uyezd"] = m.group(1)
    return all_persons, all_edges


def deduplicate(persons: list[dict]) -> tuple[list[dict], dict[int, int]]:
    sorted_persons = sorted(
        persons,
        key=lambda p: (
            (10 if p.get("first_name") else 0)
            + (5 if p.get("patronymic") else 0)
            + (4 if p.get("surname") else 0)
            + (3 if p.get("settlement") else 0)
            + (2 if p.get("landowner") else 0)
        ),
        reverse=True,
    )

    unique: list[dict] = []
    temp_id_to_final: dict[int, int] = {}

    for p in sorted_persons:
        matched = False
        for existing in unique:
            if p["first_name"] != existing["first_name"]:
                continue
            if (p.get("patronymic") or None) != (existing.get("patronymic") or None):
                continue

            sp = p.get("settlement") or None
            se = existing.get("settlement") or None
            lp = p.get("landowner") or None
            le = existing.get("landowner") or None
            surnp = p.get("surname") or None
            surne = existing.get("surname") or None

            conflict = False
            if sp and se and sp != se:
                conflict = True
            if lp and le and lp != le:
                conflict = True
            if surnp and surne and surnp != surne:
                conflict = True

            # Role-based conflict: a newborn cannot be a parent within 5-10 years
            p_rt = p.get("relation_type", "")
            ex_roles = existing.get("all_roles", [existing.get("relation_type", "")])
            if p_rt == "Родившийся" and "Родитель" in ex_roles:
                conflict = True
            if p_rt == "Родитель" and "Родившийся" in ex_roles:
                conflict = True
            # Two newborns with the same name are different people — born once
            if p_rt == "Родившийся" and "Родившийся" in ex_roles:
                conflict = True
            # A newborn cannot marry within 10 years
            if p_rt == "Родившийся" and ("Жених" in ex_roles or "Невеста" in ex_roles):
                conflict = True
            if p_rt in ("Жених", "Невеста") and "Родившийся" in ex_roles:
                conflict = True
            # A child under ~5 cannot be a godparent
            if p_rt == "Родившийся" and "Восприемник" in ex_roles:
                conflict = True
            if p_rt == "Восприемник" and "Родившийся" in ex_roles:
                conflict = True

            if conflict:
                continue

            matched = True
            temp_id_to_final[p["_temp_id"]] = existing["id"]
            # Accumulate roles from the merged record
            rt = p.get("relation_type")
            if rt and rt not in existing.setdefault("all_roles", [existing.get("relation_type", "")]):
                existing["all_roles"].append(rt)
            rct = p.get("record_type")
            if rct and rct not in existing.setdefault("all_record_types", [existing.get("record_type", "")]):
                existing["all_record_types"].append(rct)
            aurl = p.get("_archive_url")
            if aurl and aurl not in existing.get("archive_urls", []):
                existing.setdefault("archive_urls", []).append(aurl)
            src = p.get("_source")
            if src and src not in existing.get("sources", []):
                existing.setdefault("sources", []).append(src)
            break

        if matched:
            temp_id_to_final[p["_temp_id"]] = existing["id"]
        else:
            new_id = len(unique) + 1
            p["id"] = new_id
            rt = p.get("relation_type")
            rct = p.get("record_type")
            p.setdefault("all_roles", [rt] if rt else [])
            p.setdefault("all_record_types", [rct] if rct else [])
            archive_url = p.get("_archive_url")
            p["archive_urls"] = [archive_url] if archive_url else []
            source = p.get("_source")
            p["sources"] = [source] if source else []
            unique.append({k: v for k, v in p.items() if not k.startswith("_")})
            temp_id_to_final[p["_temp_id"]] = new_id

    return unique, temp_id_to_final


def extract_year_from_filename(fpath: Path) -> int | None:
    name = fpath.stem
    m = re.search(r"(\d{4})", name)
    if m:
        return int(m.group(1))
    return None


def read_page_file(fpath: Path) -> tuple[int, list[dict]]:
    data = json.loads(fpath.read_text(encoding="utf-8"))
    if "year" in data:
        year = data["year"] or 0
    else:
        year = extract_year_from_filename(fpath) or 0
    entries = data.get("entries", [])
    if not entries and "api_response" in data:
        entries = data["api_response"].get("entries", [])
    return year, entries


def main():
    print("=" * 60)
    print("Parse raw API → nodes + edges")
    print("=" * 60)

    raw_dirs = sorted(RAW_API_DIR.iterdir()) if RAW_API_DIR.exists() else []
    if not raw_dirs:
        print("No raw_api data found. Run scraper.py first.")
        return

    all_persons = []
    all_edges = []
    temp_id_counter = [0]

    for uuid_dir in raw_dirs:
        if not uuid_dir.is_dir():
            continue
        uuid = uuid_dir.name
        page_files = sorted(uuid_dir.glob("page_*.json"))
        if not page_files:
            continue

        print(f"\n{uuid[:12]}.. ({len(page_files)} files)")

        for fpath in page_files:
            year, entries = read_page_file(fpath)
            m = re.search(r"page_(\d+)", fpath.stem)
            page_num = int(m.group(1)) if m else 0
            data = {"entries": entries}
            persons, edges = process_page_data(data, year, temp_id_counter, uuid, page_num)
            print(f"  pg {page_num}: {len(persons)}p {len(edges)}e")
            all_persons.extend(persons)
            all_edges.extend(edges)

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

    OUTPUT_NODES.write_text(
        json.dumps(unique_persons, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    OUTPUT_EDGES.write_text(
        json.dumps(final_edges, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nSaved: {OUTPUT_NODES.name} ({len(unique_persons)} nodes)")
    print(f"Saved: {OUTPUT_EDGES.name} ({len(final_edges)} edges)")
    print("Done!")


if __name__ == "__main__":
    main()
