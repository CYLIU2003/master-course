from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable
from typing import Any


def normalize_for_python(obj: Any) -> Any:
    """Parquet/Arrow 由来の型を Python ネイティブ型に再帰変換する。

    numpy.ndarray / numpy.generic が BFF 層に漏れて真偽判定クラッシュを
    起こす問題を防ぐため、loader の公開関数出口で必ず呼ぶこと。
    """
    try:
        import numpy as np
        if isinstance(obj, np.ndarray):
            return [normalize_for_python(v) for v in obj.tolist()]
        if isinstance(obj, np.generic):
            return obj.item()
    except ImportError:
        pass
    if isinstance(obj, dict):
        return {k: normalize_for_python(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_for_python(v) for v in obj]
    return obj


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
