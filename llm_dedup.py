#!/usr/bin/env python3
"""
LLM-based person deduplication for draw-church.

Uses an LLM to classify whether two person records from 19th-century
Russian parish registers represent the same individual. The deterministic
algorithm in parsing/dedup.py is conservative (any difference in
surname/settlement/landowner = different person), which leads to false
negatives when OCR errors, spelling variants, or context-resolution
failures produce slightly different attributes for the same person.

This tool:
  1. Generates candidate pairs (same-bucket and fuzzy-name strategies)
     that the deterministic algorithm kept separate
  2. Builds rich relationship context (shared spouses, children,
     godchildren, witnesses) for each candidate pair
  3. Sends batched prompts to an LLM API for classification
  4. Outputs merge suggestions consumable by merge_persons.py

Usage:
  python3 llm_dedup.py candidates [--strategy same-bucket|fuzzy|all]
      [--limit N] [--min-score N] [--json]
      Generate candidate pairs as JSON, print to stdout.

  python3 llm_dedup.py classify [--strategy same-bucket|fuzzy|all]
      [--limit N] [--min-score N] [--batch-size N] [--output FILE]
      Generate candidates, call LLM, print merge suggestions as JSON.

  python3 llm_dedup.py apply [--strategy same-bucket|fuzzy|all]
      [--limit N] [--min-score N] [--batch-size N] [--dry-run]
      Generate candidates, call LLM, auto-apply HIGH-confidence merges
      via merge_persons.py. Records in manual-merges.json.

  python3 llm_dedup.py stats
      Print deduplication statistics.

Environment variables:
  LLM_DEDUP_API_KEY   – API key (required for classify/apply)
  LLM_DEDUP_API_BASE  – API base URL (default: https://api.openai.com/v1)
  LLM_DEDUP_MODEL     – Model name (default: gpt-4o)
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).parent
NODES_PATH = BASE_DIR / "all-nodes.json"
EDGES_PATH = BASE_DIR / "all-edges.json"

# ── LLM configuration ─────────────────────────────────────────────
API_KEY = os.environ.get("LLM_DEDUP_API_KEY", "")
API_BASE = os.environ.get("LLM_DEDUP_API_BASE", "https://api.openai.com/v1")
MODEL = os.environ.get("LLM_DEDUP_MODEL", "gpt-4o")

# ── Domain rules injected into every prompt ────────────────────────

DOMAIN_RULES = """## Domain Knowledge for 19th-century Russian Parish Registers

1. **Godparent age**: A godparent (восприемник) must be at least 10 years old
   at the time of the baptism. If a person appears as a godparent in year Y,
   they must have been born no later than Y-10.

2. **Name variants**: These are the SAME name and indicate the SAME person:
   - Георгий = Егор = Егорий = Юрий
   - Иоанн = Иван
   - Феодор = Федор
   - Косма = Кузьма
   - Иоаким = Аким
   - Иулиания = Ульяна
   - Онисим = Анисим
   - Осип = Иосиф
   - Кодрат = Кондрат
   - Димитрий = Дмитрий
   - Феодосий = Федосей
   - Агриппина = Аграфена
   - Ксения = Аксинья

3. **Patronymic variants**: These patronymic forms refer to the SAME father:
   - Иванов = Иоаннов
   - Афанасьев = Афонасьев
   - Феодоров = Федоров
   - Осипов = Иосифов
   - Онисимов = Анисимов

4. **Landowner variants**: Different grammatical cases or minor spelling
   differences in landowner names are the SAME landowner:
   - Новосильцовой = Новосильцевой = Новосильцова
   - Ешевского = Ежевского (OCR ж↔ш confusion)
   - Кроткова = Кротковой

5. **"та же деревня" / "то же сельцо"**: These are context references that
   resolve to the previous settlement. If one person has the resolved name
   and another has the unresolved reference, they may share the same settlement.

6. **Second marriage vs same person**: If two records share a child (both are
   parents of the same child via 'married_to' → 'child_of' chain), and the
   persons have the same or similar first_name+patronymic, they are almost
   certainly the SAME person recorded differently — NOT a second marriage.
   Specifically: if person A and person B are both married to the same spouse,
   they are the same person. Same-settlement + shared spouse = SAME PERSON.

7. **Social status in landowner field**: Sometimes the 'landowner' field
   contains a social status instead of an actual landowner name
   (e.g., "крестьянин", "крестьянская девица", "дворовый человек").
   These are NOT actual landowners and should be treated as null when comparing.

8. **Settlement normal forms**: Administrative hierarchy prefixes like
   "Сельцо", "Деревня", "Село", "Город" are part of the settlement type,
   not the name. "Сельцо Глазечня" and "Деревня Глазечня" may be different
   places if the type differs, but the same type + same core name = same place.

9. **Year tolerance**: The same person can appear in records spanning 20-40
   years. A person born in 1830 can appear as a parent in 1855, a witness in
   1848, and a godparent in 1852. Year differences of up to 30 years are
   normal for adults. However, a person cannot appear in records BEFORE their
   birth year (except as a newborn "Родившийся").

10. **Shared connections**: If two persons share a spouse (both married to
    the same person), they are ALMOST CERTAINLY the same person. If they
    share godchildren or witnessed the same wedding, this is strong evidence
    they are the same person — especially when combined with matching
    settlement and similar attributes."""


# ── Name equivalence dictionary ────────────────────────────────────
# Canonical form → set of equivalent variants

NAME_EQUIVALENTS: dict[str, set[str]] = {
    "Георгий": {"Георгий", "Егор", "Егорий", "Юрий"},
    "Иоанн": {"Иоанн", "Иван"},
    "Феодор": {"Феодор", "Федор"},
    "Феодосий": {"Феодосий", "Федосей"},
    "Косма": {"Косма", "Кузьма"},
    "Иоаким": {"Иоаким", "Аким"},
    "Иулиания": {"Иулиания", "Ульяна"},
    "Онисим": {"Онисим", "Анисим"},
    "Иосиф": {"Иосиф", "Осип"},
    "Кодрат": {"Кодрат", "Кондрат"},
    "Димитрий": {"Димитрий", "Дмитрий"},
    "Агриппина": {"Агриппина", "Аграфена"},
    "Ксения": {"Ксения", "Аксинья"},
    "Иаков": {"Иаков", "Яков"},
    "Иоанникий": {"Иоанникий", "Аникий"},
    "Параскева": {"Параскева", "Прасковья"},
    "Евфимий": {"Евфимий", "Ефим"},
    "Евдокия": {"Евдокия", "Авдотья"},
    "Емилиан": {"Емилиан", "Емельян"},
    "Ирина": {"Ирина", "Арина"},
    "Евфросиния": {"Евфросиния", "Афросинья"},
}

# Build reverse lookup: any variant → canonical
_NAME_TO_CANONICAL: dict[str, str] = {}
for canonical, variants in NAME_EQUIVALENTS.items():
    for v in variants:
        _NAME_TO_CANONICAL[v] = canonical


def _names_equivalent(a: str | None, b: str | None) -> bool:
    """Check if two first names or patronymics are equivalent variants."""
    if not a or not b:
        return False
    if a == b:
        return True
    ca = _NAME_TO_CANONICAL.get(a, a)
    cb = _NAME_TO_CANONICAL.get(b, b)
    return ca == cb


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two strings."""
    if len(a) < len(b):
        a, b = b, a
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def load_data(
    nodes_path: Path = NODES_PATH, edges_path: Path = EDGES_PATH
) -> tuple[list[dict], list[dict]]:
    nodes = json.loads(nodes_path.read_text(encoding="utf-8"))
    edges = json.loads(edges_path.read_text(encoding="utf-8"))
    return nodes, edges


# ── Adjacency index ────────────────────────────────────────────────


def build_adjacency(edges: list[dict]) -> dict[int, dict[str, list[int]]]:
    adj: dict[int, dict[str, list[int]]] = defaultdict(
        lambda: {
            "parents": [],
            "children": [],
            "spouses": [],
            "godchildren": [],
            "godparents": [],
            "witnessed": [],
            "witnesses": [],
            "others": [],
        }
    )
    for e in edges:
        s, t, r = e["source_id"], e["target_id"], e["relation"]
        if r == "child_of":
            adj[s]["parents"].append(t)
            adj[t]["children"].append(s)
        elif r == "married_to":
            adj[s]["spouses"].append(t)
            adj[t]["spouses"].append(s)
        elif r == "godparent_of":
            adj[s]["godchildren"].append(t)
            adj[t]["godparents"].append(s)
        elif r == "witnessed_for":
            adj[s]["witnessed"].append(t)
            adj[t]["witnesses"].append(s)
        elif r == "other":
            adj[s]["others"].append(t)
    return adj


# ── Candidate generation ───────────────────────────────────────────


def _is_social_status(landowner: str) -> bool:
    """Return True if the landowner value is actually a social status, not a landowner."""
    if not landowner:
        return False
    status_words = {
        "крестьянин",
        "крестьянка",
        "крестьянский",
        "крестьянская",
        "крестьянские",
        "дворовый",
        "дворовая",
        "дворовые",
        "солдат",
        "солдатка",
        "мещанин",
        "мещанка",
        "девица",
        "отставной",
        "рядовой",
        "унтер",
        "экономический",
        "экономическая",
    }
    lower = landowner.lower().strip()
    for sw in status_words:
        if sw in lower:
            return True
    return False


def _normalize_landowner(landowner: str | None) -> str | None:
    """Return None for social-status values, otherwise the landowner name."""
    if not landowner:
        return None
    if _is_social_status(landowner):
        return None
    return landowner.strip()


def generate_candidates(
    nodes: list[dict],
    adj: dict[int, dict[str, list[int]]],
    min_score: int = 0,
    limit: int = 500,
) -> list[dict]:
    """
    Generate candidate pairs that the deterministic algorithm kept separate.
    Returns list sorted by overlap score (highest first).
    """
    # Group by (first_name, patronymic)
    buckets: dict[tuple[str, str | None], list[dict]] = defaultdict(list)
    for n in nodes:
        key = (n.get("first_name", ""), n.get("patronymic") or None)
        buckets[key].append(n)

    multi = {k: v for k, v in buckets.items() if len(v) > 1}

    candidates = []
    seen_pairs = set()

    for _, group in multi.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                id_a, id_b = a["id"], b["id"]
                pair_key = (min(id_a, id_b), max(id_a, id_b))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                # Attribute extraction (normalize landowners)
                sa = a.get("settlement") or ""
                sb = b.get("settlement") or ""
                la = _normalize_landowner(a.get("landowner"))
                lb = _normalize_landowner(b.get("landowner"))
                sna = a.get("surname") or ""
                snb = b.get("surname") or ""

                # Must share at least one meaningful attribute OR have edge overlap
                shares_sett = bool(sa and sb and sa == sb)
                shares_land = bool(la and lb and la == lb)
                shares_surn = bool(sna and snb and sna == snb)
                shares_attr = shares_sett or shares_land or shares_surn

                # Edge overlap
                ctx_a = adj.get(id_a, {})
                ctx_b = adj.get(id_b, {})

                shared_spouses = list(set(ctx_a.get("spouses", [])) & set(ctx_b.get("spouses", [])))
                shared_children = list(
                    set(ctx_a.get("children", [])) & set(ctx_b.get("children", []))
                )
                shared_godchildren = list(
                    set(ctx_a.get("godchildren", [])) & set(ctx_b.get("godchildren", []))
                )
                shared_parents = list(set(ctx_a.get("parents", [])) & set(ctx_b.get("parents", [])))

                edge_score = (
                    len(shared_spouses) * 10
                    + len(shared_children) * 5
                    + len(shared_godchildren) * 3
                    + len(shared_parents) * 1
                )

                total_score = edge_score + (1 if shares_sett else 0) + (1 if shares_land else 0)

                if total_score < min_score:
                    continue
                if not shares_attr and edge_score == 0:
                    continue

                # Year filter
                ya = a.get("year", 0) or 0
                yb = b.get("year", 0) or 0
                if ya and yb and abs(ya - yb) > 40:
                    continue

                # Role incompatibility: a person who was born in year Y
                # cannot be a parent/godparent in a year before Y
                ba = a.get("birth_year")
                bb = b.get("birth_year")
                incompatible = False
                if ba and yb and yb < ba:
                    incompatible = True
                if bb and ya and ya < bb:
                    incompatible = True
                if incompatible:
                    continue

                candidates.append(
                    {
                        "id_a": id_a,
                        "id_b": id_b,
                        "label_a": (
                            f"{a.get('first_name', '')}"
                            f" {a.get('patronymic', '')} {sna}"
                        ).strip(),
                        "label_b": (
                            f"{b.get('first_name', '')}"
                            f" {b.get('patronymic', '')} {snb}"
                        ).strip(),
                        "sett_a": sa,
                        "sett_b": sb,
                        "land_a": la or (a.get("landowner") or ""),
                        "land_b": lb or (b.get("landowner") or ""),
                        "surn_a": sna,
                        "surn_b": snb,
                        "year_a": ya,
                        "year_b": yb,
                        "birth_year_a": a.get("birth_year"),
                        "birth_year_b": b.get("birth_year"),
                        "roles_a": a.get("all_roles", []),
                        "roles_b": b.get("all_roles", []),
                        "edge_score": edge_score,
                        "shares_settlement": shares_sett,
                        "shares_landowner": shares_land,
                        "shares_surname": shares_surn,
                        "shared_spouses": shared_spouses,
                        "shared_children": shared_children,
                        "shared_godchildren": shared_godchildren,
                        "shared_parents": shared_parents,
                        "total_score": total_score,
                    }
                )

    candidates.sort(key=lambda x: (-x["total_score"], x["label_a"]))
    return candidates[:limit]


def generate_fuzzy_candidates(
    nodes: list[dict],
    adj: dict[int, dict[str, list[int]]],
    min_score: int = 0,
    limit: int = 500,
    max_edit_distance: int = 2,
) -> list[dict]:
    """
    Generate candidates where persons have similar but not identical names
    (name variants, spelling differences, OCR errors). These would NOT be
    caught by the same-bucket strategy.
    """
    # Group by first_name only
    fn_buckets: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        fn = n.get("first_name", "")
        if fn:
            fn_buckets[fn].append(n)

    candidates = []
    seen_pairs = set()

    for _, group in fn_buckets.items():
        # Skip groups with only 1 entry
        if len(group) < 2:
            continue

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                id_a, id_b = a["id"], b["id"]
                pair_key = (min(id_a, id_b), max(id_a, id_b))

                # Already handled by same-bucket strategy
                pt_a = a.get("patronymic") or ""
                pt_b = b.get("patronymic") or ""
                if pt_a == pt_b:
                    continue

                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                # Check if patronymics are equivalent or similar
                patronymic_similar = _names_equivalent(pt_a, pt_b) or (
                    len(pt_a) >= 4
                    and len(pt_b) >= 4
                    and _edit_distance(pt_a, pt_b) <= max_edit_distance
                )
                if not patronymic_similar:
                    continue

                # Attribute overlap
                sa = a.get("settlement") or ""
                sb = b.get("settlement") or ""
                la = _normalize_landowner(a.get("landowner"))
                lb = _normalize_landowner(b.get("landowner"))
                sna = a.get("surname") or ""
                snb = b.get("surname") or ""

                shares_sett = bool(sa and sb and sa == sb)
                shares_land = bool(la and lb and la == lb)
                shares_surn = bool(sna and snb and sna == snb)

                # Edge overlap
                ctx_a = adj.get(id_a, {})
                ctx_b = adj.get(id_b, {})
                shared_spouses = list(set(ctx_a.get("spouses", [])) & set(ctx_b.get("spouses", [])))
                shared_children = list(
                    set(ctx_a.get("children", [])) & set(ctx_b.get("children", []))
                )
                shared_godchildren = list(
                    set(ctx_a.get("godchildren", [])) & set(ctx_b.get("godchildren", []))
                )
                shared_parents = list(set(ctx_a.get("parents", [])) & set(ctx_b.get("parents", [])))

                edge_score = (
                    len(shared_spouses) * 10
                    + len(shared_children) * 5
                    + len(shared_godchildren) * 3
                    + len(shared_parents) * 1
                )
                attr_score = (1 if shares_sett else 0) + (1 if shares_land else 0)
                total_score = edge_score + attr_score

                # Must have strong signal: edge overlap OR share settlement+landowner
                if total_score < min_score:
                    continue
                if edge_score == 0 and not (shares_sett and shares_land):
                    continue

                # Year filter
                ya = a.get("year", 0) or 0
                yb = b.get("year", 0) or 0
                if ya and yb and abs(ya - yb) > 40:
                    continue

                # Role incompatibility
                ba = a.get("birth_year")
                bb = b.get("birth_year")
                incompatible = False
                if ba and yb and yb < ba:
                    incompatible = True
                if bb and ya and ya < bb:
                    incompatible = True
                if incompatible:
                    continue

                candidates.append(
                    {
                        "id_a": id_a,
                        "id_b": id_b,
                        "label_a": f"{a.get('first_name', '')} {pt_a} {sna}".strip(),
                        "label_b": f"{b.get('first_name', '')} {pt_b} {snb}".strip(),
                        "sett_a": sa,
                        "sett_b": sb,
                        "land_a": la or (a.get("landowner") or ""),
                        "land_b": lb or (b.get("landowner") or ""),
                        "surn_a": sna,
                        "surn_b": snb,
                        "year_a": ya,
                        "year_b": yb,
                        "birth_year_a": a.get("birth_year"),
                        "birth_year_b": b.get("birth_year"),
                        "roles_a": a.get("all_roles", []),
                        "roles_b": b.get("all_roles", []),
                        "edge_score": edge_score,
                        "shares_settlement": shares_sett,
                        "shares_landowner": shares_land,
                        "shares_surname": shares_surn,
                        "shared_spouses": shared_spouses,
                        "shared_children": shared_children,
                        "shared_godchildren": shared_godchildren,
                        "shared_parents": shared_parents,
                        "total_score": total_score,
                        "_patronymic_equiv": _names_equivalent(pt_a, pt_b),
                        "_patronymic_dist": _edit_distance(pt_a, pt_b)
                        if not _names_equivalent(pt_a, pt_b)
                        else 0,
                    }
                )

    candidates.sort(key=lambda x: (-x["total_score"], x["label_a"]))
    return candidates[:limit]


# ── Context enrichment ─────────────────────────────────────────────


def _resolve_node_label(nodes_by_id: dict[int, dict], nid: int) -> str:
    n = nodes_by_id.get(nid)
    if not n:
        return f"id={nid}"
    return (
        f"{n.get('first_name', '?')} {n.get('patronymic', '?')} "
        f"{n.get('surname', '') or ''} ({n.get('settlement', '?')})".strip()
    )


def build_candidate_context(
    candidate: dict,
    nodes_by_id: dict[int, dict],
    adj: dict[int, dict[str, list[int]]],
) -> str:
    """Build a text description of why two nodes might be the same person."""
    lines = []

    lines.append(f"## Person A: id={candidate['id_a']} — {candidate['label_a']}")
    lines.append(f"- Year: {candidate['year_a']}")
    lines.append(f"- Settlement: {candidate['sett_a'] or '(none)'}")
    lines.append(f"- Landowner: {candidate['land_a'] or '(none)'}")
    lines.append(f"- Surname: {candidate['surn_a'] or '(none)'}")
    lines.append(f"- Roles held: {', '.join(candidate['roles_a'])}")
    if candidate["birth_year_a"]:
        lines.append(f"- Birth year: {candidate['birth_year_a']}")

    ctx_a = adj.get(candidate["id_a"], {})
    if ctx_a.get("spouses"):
        sp_labels = [_resolve_node_label(nodes_by_id, s) for s in ctx_a["spouses"]]
        lines.append(f"- Spouse(s): {', '.join(sp_labels)}")
    if ctx_a.get("children"):
        ch_labels = [_resolve_node_label(nodes_by_id, s) for s in ctx_a["children"]]
        lines.append(f"- Children: {', '.join(ch_labels[:5])}{'...' if len(ch_labels) > 5 else ''}")
    if ctx_a.get("parents"):
        p_labels = [_resolve_node_label(nodes_by_id, s) for s in ctx_a["parents"]]
        lines.append(f"- Parents: {', '.join(p_labels)}")
    if ctx_a.get("godchildren"):
        g_labels = [_resolve_node_label(nodes_by_id, s) for s in ctx_a["godchildren"]]
        lines.append(
            f"- Godchildren: {', '.join(g_labels[:5])}{'...' if len(g_labels) > 5 else ''}"
        )

    lines.append("")
    lines.append(f"## Person B: id={candidate['id_b']} — {candidate['label_b']}")
    lines.append(f"- Year: {candidate['year_b']}")
    lines.append(f"- Settlement: {candidate['sett_b'] or '(none)'}")
    lines.append(f"- Landowner: {candidate['land_b'] or '(none)'}")
    lines.append(f"- Surname: {candidate['surn_b'] or '(none)'}")
    lines.append(f"- Roles held: {', '.join(candidate['roles_b'])}")
    if candidate["birth_year_b"]:
        lines.append(f"- Birth year: {candidate['birth_year_b']}")

    ctx_b = adj.get(candidate["id_b"], {})
    if ctx_b.get("spouses"):
        sp_labels = [_resolve_node_label(nodes_by_id, s) for s in ctx_b["spouses"]]
        lines.append(f"- Spouse(s): {', '.join(sp_labels)}")
    if ctx_b.get("children"):
        ch_labels = [_resolve_node_label(nodes_by_id, s) for s in ctx_b["children"]]
        lines.append(f"- Children: {', '.join(ch_labels[:5])}{'...' if len(ch_labels) > 5 else ''}")
    if ctx_b.get("parents"):
        p_labels = [_resolve_node_label(nodes_by_id, s) for s in ctx_b["parents"]]
        lines.append(f"- Parents: {', '.join(p_labels)}")
    if ctx_b.get("godchildren"):
        g_labels = [_resolve_node_label(nodes_by_id, s) for s in ctx_b["godchildren"]]
        lines.append(
            f"- Godchildren: {', '.join(g_labels[:5])}{'...' if len(g_labels) > 5 else ''}"
        )

    # Conflict analysis
    lines.append("")
    lines.append("## Why the deterministic algorithm kept them separate")
    conflicts = []
    if candidate["sett_a"] and candidate["sett_b"] and candidate["sett_a"] != candidate["sett_b"]:
        conflicts.append(
            f"- Settlement conflict: '{candidate['sett_a']}' vs '{candidate['sett_b']}'"
        )
    la_norm = _normalize_landowner(candidate["land_a"])
    lb_norm = _normalize_landowner(candidate["land_b"])
    if la_norm and lb_norm and la_norm != lb_norm:
        conflicts.append(f"- Landowner conflict: '{la_norm}' vs '{lb_norm}'")
    if candidate["surn_a"] and candidate["surn_b"] and candidate["surn_a"] != candidate["surn_b"]:
        conflicts.append(f"- Surname conflict: '{candidate['surn_a']}' vs '{candidate['surn_b']}'")
    if not conflicts:
        conflicts.append("- (No direct conflict detected; kept separate during initial parsing)")

    for c in conflicts:
        lines.append(c)

    # Shared connections
    lines.append("")
    lines.append("## Shared Connections")
    if candidate["shared_spouses"]:
        sp_labels = [_resolve_node_label(nodes_by_id, s) for s in candidate["shared_spouses"]]
        lines.append(f"- **Shared spouse(s):** {', '.join(sp_labels)} ← STRONGEST signal")
    if candidate["shared_children"]:
        ch_labels = [_resolve_node_label(nodes_by_id, s) for s in candidate["shared_children"]]
        lines.append(f"- Shared children: {', '.join(ch_labels)}")
    if candidate["shared_godchildren"]:
        g_labels = [_resolve_node_label(nodes_by_id, s) for s in candidate["shared_godchildren"]]
        lines.append(f"- Shared godchildren: {', '.join(g_labels)}")
    if candidate["shared_parents"]:
        p_labels = [_resolve_node_label(nodes_by_id, s) for s in candidate["shared_parents"]]
        lines.append(f"- Shared parents: {', '.join(p_labels)}")
    if not any(
        [
            candidate["shared_spouses"],
            candidate["shared_children"],
            candidate["shared_godchildren"],
            candidate["shared_parents"],
        ]
    ):
        lines.append("- No shared connections found.")
        if candidate["shares_settlement"]:
            lines.append(
                "- BUT they share the same settlement — possible same person with missing data."
            )

    return "\n".join(lines)


# ── LLM interaction ────────────────────────────────────────────────


def _call_llm(prompt: str) -> str:
    """Call the LLM API. Returns the response text."""
    if not API_KEY:
        raise RuntimeError("LLM_DEDUP_API_KEY not set. Set it via environment variable.")

    url = f"{API_BASE.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a historian specializing in 19th-century"
                        " Russian genealogy. Answer concisely and precisely."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(2**attempt * 5)
                continue
            raise
        except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
            if attempt < 2:
                time.sleep(2)
                continue
            raise

    raise RuntimeError("LLM API call failed after 3 attempts")


def _build_batch_prompt(
    batch: list[dict],
    nodes_by_id: dict[int, dict],
    adj: dict[int, dict[str, list[int]]],
    batch_start_idx: int,
) -> str:
    """Build a prompt for classifying a batch of candidate pairs."""
    lines = [
        "You are classifying pairs of persons from 19th-century Russian parish registers.",
        "",
        DOMAIN_RULES,
        "",
        f"## Task: Classify {len(batch)} candidate pairs",
        "",
        "For each pair, determine if Person A and Person B are the SAME person",
        "or DIFFERENT people. Use the domain rules above and the relationship",
        "context provided.",
        "",
        "Respond with a JSON array. Each element must have these fields:",
        '  {"pair_index": <n>, "decision": "SAME"|"DIFFERENT",',
        '   "confidence": "high"|"medium"|"low",',
        '   "reasoning": "<one sentence in Russian>"}',
        "",
        "---",
        "",
    ]

    for i, cand in enumerate(batch):
        lines.append(f"### Pair {batch_start_idx + i + 1}")
        lines.append(build_candidate_context(cand, nodes_by_id, adj))
        lines.append("---")
        lines.append("")

    lines.append("Now respond with the JSON array for all pairs above.")
    return "\n".join(lines)


def _parse_llm_response(response: str, batch_size: int) -> list[dict]:
    """Parse the LLM's JSON response into a list of classification results."""
    # Try to extract JSON array from the response
    json_match = re.search(r"\[.*\]", response, re.DOTALL)
    if not json_match:
        print(f"  WARNING: Could not parse LLM response. Raw:\n{response[:500]}", file=sys.stderr)
        return []

    try:
        results = json.loads(json_match.group(0))
        if not isinstance(results, list):
            return []
        return results
    except json.JSONDecodeError:
        # Try to fix common JSON issues
        cleaned = json_match.group(0)
        cleaned = re.sub(r",\s*]", "]", cleaned)
        cleaned = re.sub(r",\s*}", "}", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"  WARNING: JSON parse error. Raw:\n{response[:500]}", file=sys.stderr)
            return []


def classify_candidates(
    candidates: list[dict],
    nodes: list[dict],
    adj: dict[int, dict[str, list[int]]],
    batch_size: int = 15,
) -> list[dict]:
    """
    Classify candidate pairs using LLM. Returns list of merge suggestions.
    """
    nodes_by_id = {n["id"]: n for n in nodes}
    results = []
    api_errors: list[dict] = []

    for batch_start in range(0, len(candidates), batch_size):
        batch = candidates[batch_start : batch_start + batch_size]
        prompt = _build_batch_prompt(batch, nodes_by_id, adj, batch_start)

        print(
            f"  Sending batch {batch_start // batch_size + 1}/"
            f"{(len(candidates) + batch_size - 1) // batch_size} "
            f"({len(batch)} pairs, ~{len(prompt)} chars)...",
            file=sys.stderr,
        )

        try:
            response = _call_llm(prompt)
        except (urllib.error.URLError, OSError, json.JSONDecodeError, RuntimeError) as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            api_errors.append(
                {
                    "batch_start": batch_start,
                    "batch_size": len(batch),
                    "error": str(e),
                }
            )
            continue

        parsed = _parse_llm_response(response, len(batch))
        if len(parsed) != len(batch):
            print(
                f"  WARNING: Expected {len(batch)} results, got {len(parsed)}",
                file=sys.stderr,
            )

        for item in parsed:
            idx = item.get("pair_index", -1) - batch_start - 1
            if 0 <= idx < len(batch):
                cand = batch[idx]
                result = {
                    "id_a": cand["id_a"],
                    "id_b": cand["id_b"],
                    "label_a": cand["label_a"],
                    "label_b": cand["label_b"],
                    "decision": item.get("decision", "DIFFERENT"),
                    "confidence": item.get("confidence", "low"),
                    "reasoning": item.get("reasoning", ""),
                    "edge_score": cand["edge_score"],
                    "shares_settlement": cand["shares_settlement"],
                    "shares_landowner": cand["shares_landowner"],
                    "shared_spouses": cand["shared_spouses"],
                }
                results.append(result)

        time.sleep(1)  # Rate limiting

    if api_errors:
        print(
            f"  {len(api_errors)} batch(es) failed due to API errors",
            file=sys.stderr,
        )
        for ae in api_errors:
            print(
                f"    batch starting at index {ae['batch_start']}: {ae['error']}", file=sys.stderr
            )

    return results


# ── Output / Apply ─────────────────────────────────────────────────


def build_merge_groups(classified: list[dict]) -> list[dict]:
    """Group transitive SAME pairs into merge clusters."""
    same_pairs = [
        p for p in classified if p["decision"] == "SAME" and p["confidence"] in ("high", "medium")
    ]

    # Union-Find
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: int, y: int):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    all_ids = set()
    for p in same_pairs:
        union(p["id_a"], p["id_b"])
        all_ids.add(p["id_a"])
        all_ids.add(p["id_b"])

    groups: dict[int, list[int]] = defaultdict(list)
    for nid in all_ids:
        groups[find(nid)].append(nid)

    merge_suggestions = []
    for _, members in groups.items():
        if len(members) < 2:
            continue
        # Target = lowest ID, sources = rest
        members.sort()
        target = members[0]
        sources = members[1:]

        # Gather reasoning
        reasons = []
        for p in same_pairs:
            if p["id_a"] in members and p["id_b"] in members:
                reasons.append(p["reasoning"])

        merge_suggestions.append(
            {
                "target_id": target,
                "source_ids": sources,
                "members": members,
                "reasoning": "; ".join(reasons[:5]),
            }
        )

    return merge_suggestions


def apply_merges(
    merge_suggestions: list[dict],
    nodes: list[dict],
    edges: list[dict],
    nodes_path: Path = NODES_PATH,
    edges_path: Path = EDGES_PATH,
    dry_run: bool = False,
):
    """Apply merge suggestions by directly merging in-memory data and writing back."""
    sys.path.insert(0, str(BASE_DIR))
    from merge_persons import backup, dump_json, load_json, merge_persons, record_merge

    manifest_path = BASE_DIR / "manual-merges.json"

    if not dry_run:
        backup()

    manifest = load_json(manifest_path) if manifest_path.exists() else []

    for sg in merge_suggestions:
        print(f"\n  Merging → target id={sg['target_id']}")
        for src_id in sg["source_ids"]:
            print(f"    source id={src_id} → target id={sg['target_id']}")
            print(f"    Reason: {sg['reasoning'][:120]}")

            if not dry_run:
                src, tgt_pre = merge_persons(nodes, edges, src_id, sg["target_id"])
                if src is not None:
                    record_merge(manifest, src, tgt_pre, sg["reasoning"])

    if not dry_run:
        dump_json(nodes, nodes_path)
        dump_json(edges, edges_path)
        print(
            f"\n  Saved: {nodes_path.name} ({len(nodes)} nodes), "
            f"{edges_path.name} ({len(edges)} edges)"
        )


# ── Commands ───────────────────────────────────────────────────────


def cmd_stats():
    nodes_path, edges_path = _parse_io_paths(sys.argv[2:])
    nodes, edges = load_data(nodes_path, edges_path)
    adj = build_adjacency(edges)

    buckets: dict[tuple, list] = defaultdict(list)
    for n in nodes:
        key = (n.get("first_name", ""), n.get("patronymic") or None)
        buckets[key].append(n)

    multi = {k: v for k, v in buckets.items() if len(v) > 1}
    total_multi = sum(len(v) for v in multi.values())

    candidates = generate_candidates(nodes, adj, min_score=0, limit=10000)
    fuzzy = generate_fuzzy_candidates(nodes, adj, min_score=0, limit=10000)

    high_score = [c for c in candidates if c["total_score"] >= 3]
    with_spouse = [c for c in candidates if c["shared_spouses"]]
    with_children = [c for c in candidates if c["shared_children"]]
    with_godchildren = [c for c in candidates if c["shared_godchildren"]]

    fuzzy_high = [c for c in fuzzy if c["total_score"] >= 3]
    fuzzy_spouse = [c for c in fuzzy if c["shared_spouses"]]

    print(f"Total nodes:        {len(nodes)}")
    print(f"Total edges:        {len(edges)}")
    print(f"Total buckets:      {len(buckets)}")
    print(f"Multi-entry buckets: {len(multi)}")
    print(f"Persons in multi:   {total_multi} ({100 * total_multi / len(nodes):.1f}%)")
    print("---")
    print(f"Same-bucket candidates:    {len(candidates)}")
    print(f"  High-score (≥3):          {len(high_score)}")
    print(f"  With shared spouse(s):    {len(with_spouse)}")
    print(f"  With shared child(ren):   {len(with_children)}")
    print(f"  With shared godchild(ren): {len(with_godchildren)}")
    print("---")
    print(f"Fuzzy-name candidates:     {len(fuzzy)}")
    print(f"  High-score (≥3):          {len(fuzzy_high)}")
    print(f"  With shared spouse(s):    {len(fuzzy_spouse)}")


def _parse_io_paths(args: list[str]) -> tuple[Path, Path]:
    """Extract --nodes and --edges from args. Returns (nodes_path, edges_path)."""
    nodes_path = NODES_PATH
    edges_path = EDGES_PATH
    i = 0
    while i < len(args):
        if args[i] == "--nodes" and i + 1 < len(args):
            nodes_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--edges" and i + 1 < len(args):
            edges_path = Path(args[i + 1])
            i += 2
        else:
            i += 1
    return nodes_path, edges_path


def _strip_io_flags(args: list[str]) -> list[str]:
    """Remove --nodes/--edges flags from args, returning remaining args."""
    result = []
    i = 0
    while i < len(args):
        if args[i] in ("--nodes", "--edges") and i + 1 < len(args):
            i += 2
        else:
            result.append(args[i])
            i += 1
    return result


def _parse_strategy_flag(args: list[str]) -> str:
    """Extract --strategy value from args. Default: 'all'."""
    for i, a in enumerate(args):
        if a == "--strategy" and i + 1 < len(args):
            return args[i + 1]
    return "all"


def cmd_candidates(args: list[str]):
    limit = 500
    min_score = 0
    output_json = False
    strategy = _parse_strategy_flag(args)
    nodes_path, edges_path = _parse_io_paths(args)
    args = _strip_io_flags(args)

    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--min-score" and i + 1 < len(args):
            min_score = int(args[i + 1])
            i += 2
        elif args[i] == "--strategy":
            i += 2
        elif args[i] == "--json":
            output_json = True
            i += 1
        else:
            i += 1

    nodes, edges = load_data(nodes_path, edges_path)
    adj = build_adjacency(edges)

    candidates = []
    if strategy in ("same-bucket", "all"):
        candidates.extend(generate_candidates(nodes, adj, min_score=min_score, limit=limit))
    if strategy in ("fuzzy", "all"):
        candidates.extend(generate_fuzzy_candidates(nodes, adj, min_score=min_score, limit=limit))

    # Deduplicate by pair key and re-sort
    seen = set()
    unique = []
    for c in sorted(candidates, key=lambda x: (-x["total_score"], x["label_a"])):
        key = (min(c["id_a"], c["id_b"]), max(c["id_a"], c["id_b"]))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    candidates = unique[:limit]

    if output_json:
        print(json.dumps(candidates, ensure_ascii=False, indent=2))
    else:
        for i, c in enumerate(candidates):
            extra = ""
            if c.get("_patronymic_equiv"):
                extra = " [PATRONYMIC EQUIVALENT]"
            elif c.get("_patronymic_dist"):
                extra = f" [patr.dist={c['_patronymic_dist']}]"
            print(
                f"[{i + 1}] score={c['total_score']} edge={c['edge_score']} | "
                f"{c['label_a']} (id={c['id_a']}) vs {c['label_b']} (id={c['id_b']}){extra}"
            )
            if c["shared_spouses"]:
                print(f"    SHARED SPOUSE: {c['shared_spouses']}")
            if c["shared_children"]:
                print(f"    SHARED CHILDREN: {c['shared_children']}")
            if c["shared_godchildren"]:
                print(f"    SHARED GODCHILDREN: {c['shared_godchildren']}")
            if c["shares_settlement"]:
                print(f"    Same settlement: {c['sett_a']}")
            if c["shares_landowner"]:
                print(f"    Same landowner: {c['land_a']}")
            print()


def cmd_classify(args: list[str]):
    nodes_path, edges_path = _parse_io_paths(args)
    args = _strip_io_flags(args)

    limit = 100
    min_score = 1
    batch_size = 15
    output_file = None
    strategy = _parse_strategy_flag(args)

    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--min-score" and i + 1 < len(args):
            min_score = int(args[i + 1])
            i += 2
        elif args[i] == "--batch-size" and i + 1 < len(args):
            batch_size = int(args[i + 1])
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output_file = args[i + 1]
            i += 2
        elif args[i] == "--strategy":
            i += 2
        else:
            i += 1

    if not API_KEY:
        print("ERROR: LLM_DEDUP_API_KEY environment variable is required.", file=sys.stderr)
        print("Set it via: export LLM_DEDUP_API_KEY=your-key", file=sys.stderr)
        sys.exit(1)

    nodes, edges = load_data(nodes_path, edges_path)
    adj = build_adjacency(edges)

    candidates = []
    if strategy in ("same-bucket", "all"):
        candidates.extend(generate_candidates(nodes, adj, min_score=min_score, limit=limit))
    if strategy in ("fuzzy", "all"):
        candidates.extend(generate_fuzzy_candidates(nodes, adj, min_score=min_score, limit=limit))

    seen = set()
    unique = []
    for c in sorted(candidates, key=lambda x: (-x["total_score"], x["label_a"])):
        key = (min(c["id_a"], c["id_b"]), max(c["id_a"], c["id_b"]))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    candidates = unique[:limit]

    print(
        f"Generated {len(candidates)} candidates (min_score={min_score}, limit={limit})",
        file=sys.stderr,
    )
    print(f"Using model: {MODEL} at {API_BASE}", file=sys.stderr)

    results = classify_candidates(candidates, nodes, adj, batch_size=batch_size)

    same = [r for r in results if r["decision"] == "SAME"]
    print(
        f"\nResults: {len(same)} SAME, {len(results) - len(same)} DIFFERENT out of {len(results)}",
        file=sys.stderr,
    )

    merge_groups = build_merge_groups(results)
    print(f"Merge groups: {len(merge_groups)}", file=sys.stderr)

    output = {
        "model": MODEL,
        "total_candidates": len(candidates),
        "total_classified": len(results),
        "same_count": len(same),
        "classifications": results,
        "merge_groups": merge_groups,
    }

    if output_file:
        Path(output_file).write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Saved to {output_file}", file=sys.stderr)
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_apply(args: list[str]):
    nodes_path, edges_path = _parse_io_paths(args)
    args = _strip_io_flags(args)

    limit = 100
    min_score = 1
    batch_size = 15
    dry_run = False
    strategy = _parse_strategy_flag(args)

    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--min-score" and i + 1 < len(args):
            min_score = int(args[i + 1])
            i += 2
        elif args[i] == "--batch-size" and i + 1 < len(args):
            batch_size = int(args[i + 1])
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        elif args[i] == "--strategy":
            i += 2
        else:
            i += 1

    if not API_KEY:
        print("ERROR: LLM_DEDUP_API_KEY environment variable is required.", file=sys.stderr)
        print("Set it via: export LLM_DEDUP_API_KEY=your-key", file=sys.stderr)
        sys.exit(1)

    nodes, edges = load_data(nodes_path, edges_path)
    adj = build_adjacency(edges)

    candidates = []
    if strategy in ("same-bucket", "all"):
        candidates.extend(generate_candidates(nodes, adj, min_score=min_score, limit=limit))
    if strategy in ("fuzzy", "all"):
        candidates.extend(generate_fuzzy_candidates(nodes, adj, min_score=min_score, limit=limit))

    seen = set()
    unique = []
    for c in sorted(candidates, key=lambda x: (-x["total_score"], x["label_a"])):
        key = (min(c["id_a"], c["id_b"]), max(c["id_a"], c["id_b"]))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    candidates = unique[:limit]

    print(f"Generated {len(candidates)} candidates", file=sys.stderr)
    print(f"Using model: {MODEL}", file=sys.stderr)

    results = classify_candidates(candidates, nodes, adj, batch_size=batch_size)
    merge_groups = build_merge_groups(results)

    same = [r for r in results if r["decision"] == "SAME"]
    print(f"\nResults: {len(same)} SAME → {len(merge_groups)} merge groups", file=sys.stderr)

    if merge_groups:
        apply_merges(merge_groups, nodes, edges, nodes_path, edges_path, dry_run=dry_run)
    else:
        print("No merges to apply.")


# ── Main ───────────────────────────────────────────────────────────


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "stats": lambda a: cmd_stats(),
        "candidates": cmd_candidates,
        "classify": cmd_classify,
        "apply": cmd_apply,
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

    commands[command](args)


if __name__ == "__main__":
    main()
