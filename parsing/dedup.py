from .models import ROLE_BORN


def deduplicate(persons: list[dict]) -> tuple[list[dict], dict[int, int]]:
    buckets: dict[tuple[str, str | None], list[dict]] = {}
    for p in persons:
        key = (p.get("first_name", ""), p.get("patronymic") or None)
        buckets.setdefault(key, []).append(p)

    def _score(p: dict) -> int:
        return (
            (10 if p.get("first_name") else 0)
            + (5 if p.get("patronymic") else 0)
            + (4 if p.get("surname") else 0)
            + (3 if p.get("settlement") else 0)
            + (2 if p.get("landowner") else 0)
        )

    for bucket in buckets.values():
        bucket.sort(key=_score, reverse=True)

    def _conflict(e: dict, c: dict) -> bool:
        for attr in ("surname", "settlement", "landowner"):
            ev = e.get(attr) or None
            cv = c.get(attr) or None
            if ev and cv and ev != cv:
                return True

        eb = e.get("birth_year")
        cb = c.get("birth_year")
        if eb and cb and eb != cb:
            return True

        ey = e.get("year")
        cy = c.get("year")
        if eb and cy is not None and cy < eb:
            return True
        if cb and ey is not None and ey < cb:
            return True

        return False

    def _merge_into(e: dict, c: dict):
        rt = c.get("relation_type")
        if rt and rt not in e.setdefault("all_roles", []):
            e["all_roles"].append(rt)
        rct = c.get("record_type")
        if rct and rct not in e.setdefault("all_record_types", []):
            e["all_record_types"].append(rct)
        aurl = c.get("_archive_url")
        if aurl and aurl not in e.setdefault("archive_urls", []):
            e["archive_urls"].append(aurl)
        src = c.get("_source")
        if src and src not in e.setdefault("sources", []):
            e["sources"].append(src)
        if c.get("relation_type") == ROLE_BORN and c.get("year"):
            e["birth_year"] = c["year"]
            e["year"] = c["year"]

    unique: list[dict] = []
    temp_id_to_final: dict[int, int] = {}
    bucket_candidates: dict[tuple[str, str | None], list[int]] = {}

    for key, bucket in buckets.items():
        candidates = bucket_candidates.setdefault(key, [])
        for p in bucket:
            p_rt = p.get("relation_type", "")
            matched = False

            for idx in candidates:
                existing = unique[idx]
                if _conflict(existing, p):
                    continue
                matched = True
                temp_id_to_final[p["_temp_id"]] = existing["id"]
                _merge_into(existing, p)
                break

            if not matched:
                new_id = len(unique) + 1
                p["id"] = new_id
                p.setdefault("all_roles", [p_rt] if p_rt else [])
                p.setdefault(
                    "all_record_types", [p.get("record_type")] if p.get("record_type") else []
                )
                p.setdefault("archive_urls", [p["_archive_url"]] if p.get("_archive_url") else [])
                p.setdefault("sources", [p["_source"]] if p.get("_source") else [])
                if p_rt == ROLE_BORN and p.get("year"):
                    p["birth_year"] = p["year"]

                unique.append({k: v for k, v in p.items() if not k.startswith("_")})
                temp_id_to_final[p["_temp_id"]] = new_id
                candidates.append(len(unique) - 1)

    return unique, temp_id_to_final
