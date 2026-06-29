from collections import Counter

RELATION_COLORS = {
    "child_of":       "#e74c3c",
    "godparent_of":   "#f39c12",
    "married_to":     "#e91e63",
    "witnessed_for":  "#95a5a6",
    "other":          "#7f8c8d",
}

RECORD_COLORS = {
    "Родившийся":      "#3498db",
    "Бракосочетание":  "#e91e63",
}

SETTLEMENT_PALETTE = [
    "#2ecc71", "#3498db", "#9b59b6", "#f1c40f", "#e67e22", "#1abc9c",
    "#e74c3c", "#2980b9", "#8e44ad", "#27ae60", "#f39c12", "#d35400",
    "#16a085", "#c0392b", "#7f8c8d", "#2c3e50", "#00bcd4", "#ff5722",
    "#795548", "#607d8b", "#4caf50", "#ff9800", "#cddc39", "#03a9f4",
    "#e91e63", "#673ab7", "#009688", "#ffc107", "#8bc34a", "#9e9e9e",
    "#ff5252", "#536dfe",
]

NONE_SETTLEMENT_KEY = "__none__"


def assign_settlement_colours(components: list[dict]) -> dict[str, str]:
    """Count settlement frequency, assign palette colours."""
    all_settlements: Counter = Counter()
    for c in components:
        for n in c["nodes"]:
            s = n.get("settlement")
            if s:
                all_settlements[s] += 1
    ordered = [s for s, _ in all_settlements.most_common()]
    mapping: dict[str, str] = {}
    for i, s in enumerate(ordered):
        mapping[s] = SETTLEMENT_PALETTE[i % len(SETTLEMENT_PALETTE)]
    mapping[NONE_SETTLEMENT_KEY] = "#444444"
    return mapping


def assign_degrees(components: list[dict], colour_map: dict[str, str]) -> None:
    """Attach _deg and _settc to each node (mutates in-place)."""
    for c in components:
        degree_counter = Counter()
        for e in c["edges"]:
            degree_counter[e["source_id"]] += 1
            degree_counter[e["target_id"]] += 1
        for n in c["nodes"]:
            n["_deg"] = degree_counter.get(n["id"], 0)
            sett = n.get("settlement")
            n["_settc"] = colour_map.get(sett) or colour_map[NONE_SETTLEMENT_KEY]
