"""Patronymic-aware graph layout.

Two-level layout that uses only distances to separate clusters:

  1. Nodes are grouped by a normalized patronymic base (gender suffixes and
     old-orthography 'ъ' are stripped), so e.g. Иванов / Иванова / Ивановъ
     fall into one cluster.
  2. Group centers are laid out with a spring layout over the "group graph"
     (two groups are linked when a real edge connects their members).
  3. Members of each group are relaxed around the group center with a small
     force-directed pass (intra-group repulsion + springs on real edges),
     so clusters stay compact yet nodes do not fully overlap.
"""

from __future__ import annotations

import networkx as nx
import numpy as np

# Suffixes ordered longest-first so a single pass keeps the most of the stem.
_PATRONYMIC_SUFFIXES = (
    "инична",
    "овична",
    "инич",
    "ович",
    "овна",
    "евна",
    "ична",
    "ова",
    "ева",
    "ина",
    "ич",
    "ов",
    "ев",
    "ин",
)


def patronymic_base(patronymic: str | None) -> str | None:
    """Return a normalized cluster key for a patronymic, or None if absent."""
    if not patronymic:
        return None
    s = patronymic.strip().lower()
    s = s.rstrip("ъ")
    for suf in _PATRONYMIC_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def _group_centers(groups: dict[str | None, list], edges: list[dict]) -> dict:
    """Spring layout of patronymic-group centers (scaled), de-overlapped."""
    G = nx.Graph()
    for base in groups:
        G.add_node(base if base is not None else "__none__")
    for e in edges:
        a = e.get("source_base")
        b = e.get("target_base")
        a = a if a is not None else "__none__"
        b = b if b is not None else "__none__"
        if a != b:
            if G.has_edge(a, b):
                G[a][b]["weight"] += 1
            else:
                G.add_edge(a, b, weight=1)

    if len(G) <= 1:
        return {list(G.nodes())[0]: np.zeros(2)}

    pos = nx.spring_layout(G, seed=42, k=2.0, iterations=300, weight="weight")
    # scale up so neighbouring centres sit far apart relative to cluster radii
    scale = 1400.0
    centers = {base: np.array(xy) * scale for base, xy in pos.items()}

    # de-overlap pass: push centres apart so each group's disc does not overlap
    # SEPARATION: multiply the required gap so clusters sit visibly far apart
    separation = 3.0
    radii = {
        base if base is not None else "__none__": max(16.0, 3.5 * (len(ids) ** 0.45))
        for base, ids in groups.items()
    }
    keys = list(centers.keys())
    for _ in range(120):
        moved = False
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = keys[i], keys[j]
                d = centers[b] - centers[a]
                dist = np.linalg.norm(d)
                min_dist = (radii[a] + radii[b]) * separation + 30.0
                if dist < min_dist:
                    shift = (min_dist - dist) * d / (dist + 1e-9) * 0.5
                    centers[a] -= shift
                    centers[b] += shift
                    moved = True
        if not moved:
            break

    return {base: centers[base if base is not None else "__none__"] for base in groups}


def _place_members(
    ids: list, center: np.ndarray, node_map: dict, intra_edges: list[tuple], radius: float
) -> None:
    """Relax members of one group around the center (deterministic)."""
    m = len(ids)
    if m == 1:
        node_map[ids[0]]["_x"] = float(center[0])
        node_map[ids[0]]["_y"] = float(center[1])
        return

    rng = np.random.default_rng(0)
    pos = np.array([[center[0], center[1]]]) + rng.normal(0, radius * 0.3, (m, 2))
    k = 7.0
    temp = radius
    dt = 0.05

    for _ in range(90):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.sqrt(np.sum(delta**2, axis=2)) + 1e-6
        force = np.zeros_like(pos)

        # intra-group repulsion (cutoff for speed)
        rep_mask = dist < radius * 1.6
        np.fill_diagonal(rep_mask, False)
        mag = (k * k / dist) * rep_mask
        force += np.sum(mag[:, :, None] * delta / dist[:, :, None], axis=1)

        # springs on real intra-group edges
        if intra_edges:
            for i, j in intra_edges:
                d = dist[i, j]
                f = (d - k) * 0.05
                vec = delta[i, j] / d
                force[i] -= f * vec
                force[j] += f * vec

        # pull toward the group center
        force += (center - pos) * 0.18

        disp = np.linalg.norm(force, axis=1)
        step = temp * force / (disp[:, None] + 1e-9)
        pos += step * dt
        temp *= 0.97

        # keep members within the cluster disc
        from_center = pos - center
        r = np.linalg.norm(from_center, axis=1)
        over = r > radius
        if over.any():
            pos[over] = center + from_center[over] / (r[over, None] + 1e-9) * radius

    for i, nid in enumerate(ids):
        node_map[nid]["_x"] = float(pos[i, 0])
        node_map[nid]["_y"] = float(pos[i, 1])


def assign_layout(components: list[dict]) -> None:
    """Attach _x/_y to each node so same-patronymic nodes cluster together."""
    for comp in components:
        nodes = comp["nodes"]
        node_map = {n["id"]: n for n in nodes}

        # group nodes by patronymic base
        groups: dict[str | None, list] = {}
        for n in nodes:
            base = patronymic_base(n.get("patronymic"))
            groups.setdefault(base, []).append(n["id"])

        # annotate edges with endpoint bases (for the group graph)
        for e in comp["edges"]:
            src = node_map.get(e["source_id"])
            tgt = node_map.get(e["target_id"])
            e["source_base"] = patronymic_base(src.get("patronymic")) if src else None
            e["target_base"] = patronymic_base(tgt.get("patronymic")) if tgt else None

        centers = _group_centers(groups, comp["edges"])

        for base, ids in groups.items():
            center = centers.get(base, np.zeros(2))
            m = len(ids)
            # cluster radius grows slowly with group size
            radius = max(16.0, 3.5 * (m**0.45))
            idx = {nid: k for k, nid in enumerate(ids)}
            intra = []
            for e in comp["edges"]:
                i = idx.get(e["source_id"], -1)
                j = idx.get(e["target_id"], -1)
                if i >= 0 and j >= 0:
                    intra.append((i, j))
            _place_members(ids, center, node_map, intra, radius)
