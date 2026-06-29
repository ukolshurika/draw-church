import re
from pathlib import Path

_UYEZD_RE = re.compile(r"([^,]+(?:ский|цкий)?\s+уезд)")

BASE_DIR = Path(__file__).parent.parent
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

# Semantic role constants used in dedup conflict checks
ROLE_BORN = "Родившийся"
ROLE_PARENT = "Родитель"
ROLE_GODPARENT = "Восприемник"
ROLE_GROOM = "Жених"
ROLE_BRIDE = "Невеста"

