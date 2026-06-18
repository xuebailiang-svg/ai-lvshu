"""Pure merge rules for reviewed crawl evidence. Existing human data always wins."""
from copy import deepcopy
from typing import Iterable, Optional


EMPTY_VALUES = (None, "")
SCORING_PROPERTY_FIELDS = {"monthly_rent", "area_sqm", "floor"}


def merge_missing(target: dict, incoming: dict, allowed: Optional[Iterable[str]] = None) -> dict:
    result = deepcopy(target or {})
    allowed_set = set(allowed) if allowed is not None else None
    for key, value in (incoming or {}).items():
        if allowed_set is not None and key not in allowed_set:
            continue
        if result.get(key) in EMPTY_VALUES and value not in EMPTY_VALUES:
            result[key] = deepcopy(value)
    return result


def merge_competitor_rows(rows: list[dict], target_name: str, incoming: dict, metadata: dict) -> tuple[list[dict], dict]:
    result = [deepcopy(row) for row in (rows or []) if isinstance(row, dict)]
    row = next((item for item in result if str(item.get("name", "")).strip() == target_name.strip()), None)
    if row is None:
        row = {"name": target_name, "status": "manual_added", "data_source": "public_confirmed", **deepcopy(metadata)}
        result.append(row)
    merged = merge_missing(row, incoming)
    row.clear()
    row.update(merged)
    return result, row


def merge_property_conditions(existing: dict, incoming: dict) -> dict:
    return merge_missing(existing, incoming, SCORING_PROPERTY_FIELDS)
