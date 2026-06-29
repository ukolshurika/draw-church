from .models import ROLE_BORN, ROLE_PARENT, ROLE_GODPARENT, ROLE_GROOM, ROLE_BRIDE


def deduplicate(persons: list[dict]) -> tuple[list[dict], dict[int, int]]:
    # Group by (first_name, patronymic) for O(k) lookup per person.
    # Persons with different names can never match, so each bucket is
    # processed independently; the inner loop is only ~2-4 iterations
    # instead of scanning all ~4500 unique entries.
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

    unique: list[dict] = []
    temp_id_to_final: dict[int, int] = {}
    bucket_candidates: dict[tuple[str, str | None], list[int]] = {}

    for key, bucket in buckets.items():
        candidates = bucket_candidates.setdefault(key, [])
        for p in bucket:
            matched = False
            for idx in candidates:
                existing = unique[idx]

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

                p_rt = p.get("relation_type", "")
                ex_roles = existing.get("all_roles", [existing.get("relation_type")])
                if p_rt == ROLE_BORN and ROLE_PARENT in ex_roles:
                    conflict = True
                if p_rt == ROLE_PARENT and ROLE_BORN in ex_roles:
                    conflict = True
                if p_rt == ROLE_BORN and ROLE_BORN in ex_roles:
                    conflict = True
                if p_rt == ROLE_BORN and (ROLE_GROOM in ex_roles or ROLE_BRIDE in ex_roles):
                    conflict = True
                if p_rt in (ROLE_GROOM, ROLE_BRIDE) and ROLE_BORN in ex_roles:
                    conflict = True
                if p_rt == ROLE_BORN and ROLE_GODPARENT in ex_roles:
                    conflict = True
                if p_rt == ROLE_GODPARENT and ROLE_BORN in ex_roles:
                    conflict = True

                if conflict:
                    continue

                matched = True
                temp_id_to_final[p["_temp_id"]] = existing["id"]

                rt = p.get("relation_type")
                all_roles = existing.setdefault("all_roles", [])
                if not all_roles:
                    er = existing.get("relation_type")
                    if er:
                        all_roles.append(er)
                if rt and rt not in all_roles:
                    all_roles.append(rt)
                rct = p.get("record_type")
                all_rcts = existing.setdefault("all_record_types", [])
                if not all_rcts:
                    erc = existing.get("record_type")
                    if erc:
                        all_rcts.append(erc)
                if rct and rct not in all_rcts:
                    all_rcts.append(rct)
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
                candidates.append(new_id - 1)

    return unique, temp_id_to_final
