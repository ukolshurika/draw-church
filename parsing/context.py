import re

from .models import _UYEZD_RE


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
        m = _UYEZD_RE.search(s)
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
    """Try to resolve a 'то же / тоот же / та же / той же' reference using entry then global context."""
    # Detect prefix: "тот же", "того же", "той же", "то же", "та же"
    ref_type = None
    for prefix in ("тот же", "того же", "той же", "то же", "та же"):
        if s_lower.startswith(prefix):
            ref_type = s_lower[len(prefix):].strip()
            if ref_type.startswith(","):
                ref_type = ref_type[1:].strip()
            break

    if ref_type is None:
        m = re.match(r"тот\s+же\s+уезд,\s*(деревня\s+\S+)", s_lower)
        if m:
            uyezd = entry_ctx["uyezd"] or global_ctx["uyezd"]
            if uyezd:
                return f"{uyezd}, {m.group(1)}"
        return None

    # "тот же уезд [, и волость] [, Name волость], деревня/село/сельцо N"
    m = re.match(r"уезд,\s*(деревня|село|сельцо)\s+(.+)", ref_type)
    if m:
        uyezd = entry_ctx["uyezd"] or global_ctx["uyezd"]
        if uyezd:
            return f"{uyezd}, {m.group(1)} {m.group(2)}"
    m = re.match(r"уезд\s+и\s+волость,?\s*(деревня|село|сельцо)\s+(.+)", ref_type)
    if m:
        uyezd = entry_ctx["uyezd"] or global_ctx["uyezd"]
        if uyezd:
            return f"{uyezd}, {m.group(1)} {m.group(2)}"
    m = re.match(r"уезд,\s*(.+?\s+волость),\s*(деревня|село|сельцо)\s+(.+)", ref_type)
    if m:
        uyezd = entry_ctx["uyezd"] or global_ctx["uyezd"]
        if uyezd:
            return f"{uyezd}, {m.group(1)}, {m.group(2)} {m.group(3)}"

    # "тот же уезд" / "того же уезда" — just resolve the uyezd
    if ref_type in ("уезд", "уезда"):
        uyezd = entry_ctx["uyezd"] or global_ctx["uyezd"]
        if uyezd:
            return uyezd

    # "уезд, то же/та же деревня/село/сельцо" — nested context ref
    m = re.match(r"уезд,?\s*(т[оа]й?\s+же)\s+(деревн[яи]|сел[ао]|сельц[ао])", ref_type)
    if m:
        ref_inner = m.group(1) + " " + m.group(2)
        inner = _resolve_context_ref(ref_inner, entry_ctx, global_ctx)
        if inner:
            uyezd = entry_ctx["uyezd"] or global_ctx["uyezd"]
            if uyezd:
                return f"{uyezd}, {inner}"
            return inner

    # Determine which type of settlement is being referenced
    type_candidates = {
        "деревня": ("derevnya",),
        "село": ("selo",),
        "сельцо": ("selsco",),
        "деревни": ("derevnya",),
        "села": ("selo",),
        "сельца": ("selsco",),
    }
    target_keys = None
    for key, keys in type_candidates.items():
        if ref_type.startswith(key):
            target_keys = keys
            break

    if target_keys:
        for k in target_keys:
            val = entry_ctx.get(k)
            if val:
                return val
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

    return settlement
