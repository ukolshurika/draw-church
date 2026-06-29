import re


def extract_landowner(info_text: str) -> str | None:
    m = re.search(
        r"(?:помещиц[аы]|помещика)\s+(.+?)(?:\s+крестьянин|\s+крестьянка|\s*$)",
        info_text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return None
