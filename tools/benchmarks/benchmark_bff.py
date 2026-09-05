from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Dict, List


BASE_URL = "http://127.0.0.1:8000/api"
TARGETS = [
    ("health", "http://127.0.0.1:8000/health"),
    ("catalog-summary", f"{BASE_URL}/catalog/summary"),
    ("tokyu-overview", f"{BASE_URL}/catalog/operators/tokyu/overview"),
    ("tokyu-map-overview", f"{BASE_URL}/catalog/map-overview?operatorId=tokyu"),
]


def fetch(url: str) -> Dict[str, Any]:
    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": response.status,
            "elapsedMs": round(elapsed_ms, 2),
            "payloadBytes": len(body),
        }


def main() -> None:
    results: List[Dict[str, Any]] = []
    for name, url in TARGETS:
        record = {"name": name, "url": url}
        try:
            record.update(fetch(url))
        except Exception as exc:  # pragma: no cover - smoke script
            record.update({"error": str(exc)})
        results.append(record)
    print(json.dumps({"baseUrl": BASE_URL, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
