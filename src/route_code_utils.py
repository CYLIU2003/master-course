"""Utilities for route series code extraction and sorting."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

_JP_LEADING_PATTERN = re.compile(r"^([\u3040-\u309f\u30a0-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+)\s*([0-9]+)?")
_GENERIC_PATTERN = re.compile(r"^([^0-9]*?)([0-9]+)?([^0-9]*)$")


def normalize_route_code(value: Optional[str]) -> str:
    if not value:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", "", s).strip()


def parse_route_series(value: Optional[str]) -> Tuple[str, Optional[int], str]:
    """Parse route code into (prefix, number, suffix).

    Priority:
    1) Leading Japanese chars (kanji/hiragana/katakana) + optional number
    2) Generic non-digit prefix + optional number + suffix
    """
    code = normalize_route_code(value)
    if not code:
        return "", None, ""

    jp = _JP_LEADING_PATTERN.match(code)
    if jp:
        prefix = jp.group(1) or ""
        number = int(jp.group(2)) if jp.group(2) else None
        suffix = code[jp.end() :]
        return prefix, number, suffix

    m = _GENERIC_PATTERN.match(code)
    if not m:
        return code, None, ""
    prefix = m.group(1) or ""
    number = int(m.group(2)) if m.group(2) else None
    suffix = m.group(3) or ""
    return prefix, number, suffix


def extract_route_series_from_candidates(*values: Optional[str]) -> Tuple[str, str, Optional[int], str]:
    """Return (series_code, prefix, number, normalized_source) from candidates."""
    for value in values:
        source = normalize_route_code(value)
        if not source:
            continue
        prefix, number, _suffix = parse_route_series(source)
        if prefix:
            if number is None:
                return prefix, prefix, None, source
            return f"{prefix}{number:02d}", prefix, number, source
    return "", "", None, ""


def route_code_sort_key(value: Optional[str], number_desc: bool = False) -> tuple:
    code = normalize_route_code(value)
    prefix, number, suffix = parse_route_series(code)
    if number is None:
        number_rank = 10**9
    else:
        number_rank = -number if number_desc else number
    return (prefix, number_rank, suffix, code)
