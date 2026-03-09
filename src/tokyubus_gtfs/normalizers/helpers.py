"""
src.tokyubus_gtfs.normalizers.helpers — Shared normalizer utilities.

Pure functions used by all resource normalizers.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Optional


def short_id(value: Optional[str], fallback: str = "") -> str:
    """Extract the last colon-delimited segment of an ODPT URI."""
    if not value:
        return fallback
    return value.split(":")[-1]


def safe_time_hhmm(value: Any) -> Optional[str]:
    """
    Parse ODPT time string to ``HH:MM`` form.

    Accepts ``"H:MM"`` or ``"HH:MM"`` or ``"HH:MM:SS"`` formats.
    Returns None for unparseable values.
    """
    if not isinstance(value, str) or ":" not in value:
        return None
    parts = value.split(":")
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        return f"{hh:02d}:{mm:02d}"
    except (ValueError, IndexError):
        return None


def safe_time_hhmmss(value: Any) -> Optional[str]:
    """Parse to ``HH:MM:SS``.  Seconds default to 00 if missing."""
    if not isinstance(value, str) or ":" not in value:
        return None
    parts = value.split(":")
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2]) if len(parts) > 2 else 0
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    except (ValueError, IndexError):
        return None


def time_to_seconds(value: Optional[str]) -> Optional[int]:
    """
    Convert ``HH:MM`` or ``HH:MM:SS`` to seconds from midnight.

    Handles times >= 24:00 (next-day service).
    """
    if not value:
        return None
    parts = value.split(":")
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2]) if len(parts) > 2 else 0
        return hh * 3600 + mm * 60 + ss
    except (ValueError, IndexError):
        return None


def data_hash(obj: Any) -> str:
    """Deterministic SHA-256 of a JSON-serialisable object."""
    import json

    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stable_id(prefix: str, seed: str) -> str:
    """Generate a stable short hex ID from a seed string."""
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def route_color_from_seed(seed: str) -> str:
    """Generate a deterministic muted colour hex from a seed string."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    r = 64 + (int(digest[0:2], 16) % 128)
    g = 64 + (int(digest[2:4], 16) % 128)
    b = 64 + (int(digest[4:6], 16) % 128)
    return f"#{r:02x}{g:02x}{b:02x}"


def nfkc_normalize(text: str) -> str:
    """Apply NFKC normalisation (full-width digits/symbols → ASCII)."""
    return unicodedata.normalize("NFKC", text)


def extract_route_family_code(title: str) -> Optional[str]:
    """
    Derive a route family code from a Japanese route title.

    Examples:
        ``"園０１ (田園調布駅 -> 瀬田営業所)"`` → ``"園01"``
        ``"渋51 (渋谷駅 -> 若林折返所)"`` → ``"渋51"``

    Returns None if no pattern matched.
    """
    normalised = nfkc_normalize(title)
    # Pattern: optional kanji prefix + digits, before a space or paren
    match = re.match(r"^([^\s(（]+?)[\s(（]", normalised)
    if match:
        return match.group(1).strip()
    # Fallback: return the whole string if short
    if len(normalised) <= 10:
        return normalised.strip() or None
    return None


def service_id_from_odpt(calendar_short: Optional[str]) -> str:
    """Map ODPT calendar short key to GTFS service_id."""
    from ..constants import CALENDAR_MAP

    return CALENDAR_MAP.get((calendar_short or "unknown").lower(), "WEEKDAY")
