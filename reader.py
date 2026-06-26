import re
import json
from pathlib import Path

_SETTLEMENT_SYNONYMS: dict[str, str] = {
    "глазечна": "Глазечня",
    "глазечное": "Глазечня",
    "тверизино": "Тверитино",
}

_SYNONYMS_FILE = Path(__file__).parent / "settlement-synonyms.json"


def _load_synonyms() -> None:
    if _SYNONYMS_FILE.exists():
        data = json.loads(_SYNONYMS_FILE.read_text(encoding="utf-8"))
        _SETTLEMENT_SYNONYMS.update({k.lower().strip(): v for k, v in data.items()})


def _save_synonyms() -> None:
    _SYNONYMS_FILE.write_text(
        json.dumps(_SETTLEMENT_SYNONYMS, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_settlement(settlement: str | None) -> str | None:
    if not settlement:
        return settlement

    _load_synonyms()

    lower = settlement.lower().strip()
    if lower in _SETTLEMENT_SYNONYMS:
        return _SETTLEMENT_SYNONYMS[lower]

    parts = [p.strip() for p in re.split(r"[,·]", settlement)]
    changed = False
    normalized = []
    for part in parts:
        part_lower = part.lower()
        if part_lower in _SETTLEMENT_SYNONYMS:
            normalized.append(_SETTLEMENT_SYNONYMS[part_lower])
            changed = True
        else:
            words = part.split()
            norm_words = []
            for word in words:
                if word.lower() in _SETTLEMENT_SYNONYMS:
                    norm_words.append(_SETTLEMENT_SYNONYMS[word.lower()])
                    changed = True
                else:
                    norm_words.append(word)
            normalized.append(" ".join(norm_words))
    return ", ".join(normalized) if changed else settlement


def add_settlement_synonym(variant: str, canonical: str) -> None:
    _load_synonyms()
    key = variant.lower().strip()
    if key not in _SETTLEMENT_SYNONYMS:
        _SETTLEMENT_SYNONYMS[key] = canonical
        _save_synonyms()


if __name__ == "__main__":
    tests = [
        "Глазечна",
        "глазечня",
        "Серпуховский уезд, деревня Глазечна",
        "Тверитино",
        "Тверизино",
        "Пущинская волость, сельцо Тверитино",
        "сельцо Злобино",
        None,
    ]
    for t in tests:
        result = normalize_settlement(t)
        print(f"  {str(t):<55} → {result}")
