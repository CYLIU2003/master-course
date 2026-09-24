from __future__ import annotations

import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float,
                 *, radius_km: float = 6371.0088) -> float:
    """Return straight-line distance in km between two WGS84 coordinates."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    a = min(1.0, max(0.0, a))
    return 2.0 * radius_km * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
