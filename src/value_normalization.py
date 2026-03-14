from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable
from typing import Any


def normalize_text_nfkc(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple | set):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                return [value]
            return coerce_list(loaded)
        return [value]
    if isinstance(value, dict):
        return [value]
    if hasattr(value, "tolist"):
        try:
            return coerce_list(value.tolist())
        except Exception:
            pass
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def coerce_str_list(value: Any) -> list[str]:
    items = coerce_list(value)
    return [str(item) for item in items if item is not None and str(item).strip()]


def first_non_empty_list(*values: Any) -> list[Any]:
    for value in values:
        items = coerce_list(value)
        if items:
            return items
    return []
