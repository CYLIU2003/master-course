"""
src.preprocess.tariff_loader — 運賃・電力料金データ読込

- 運賃制度: 定額区間制・対距離制など
- TOU 電力料金: 時間帯別料金の読込と ElectricityPrice 変換
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.data_schema import ElectricityPrice
from src.schemas.route_entities import GeneratedTrip


# ---------------------------------------------------------------------------
# TOU 電力料金
# ---------------------------------------------------------------------------

def load_tariff_csv(
    csv_path,
) -> List[Dict[str, str]]:
    """tariff.csv を読み込む。

    CSV 形式:
        site_id, time_band, start_hour, end_hour,
        energy_price_jpy_per_kwh, demand_charge_jpy_per_kw,
        sell_back_price_jpy_per_kwh, contract_type
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"  [warn] {csv_path} が存在しません")
        return []
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_electricity_prices_from_tariff(
    tariff_rows: List[Dict[str, str]],
    site_ids: List[str],
    num_periods: int = 64,
    delta_t_min: float = 15.0,
    start_hour: float = 5.0,
    base_load_kw: float = 10.0,
) -> List[ElectricityPrice]:
    """tariff.csv → ElectricityPrice リストに変換する。

    time_band ベースの料金を各 time_idx に展開する。

    Parameters
    ----------
    tariff_rows : CSV 行リスト
    site_ids : 対象サイト一覧
    num_periods : タイムステップ数
    delta_t_min : 1ステップ [min]
    start_hour : 計画開始時間 [h]
    base_load_kw : デフォルト基礎負荷

    Returns
    -------
    List[ElectricityPrice]
    """
    # site_id → [(start_hour, end_hour, price, sell_back)] のマッピング
    tariff_map: Dict[str, List[Tuple[float, float, float, float]]] = {}
    for row in tariff_rows:
        sid = row.get("site_id", "")
        try:
            sh = float(row.get("start_hour", "0"))
            eh = float(row.get("end_hour", "24"))
            price = float(row.get("energy_price_jpy_per_kwh", "20"))
            sell = float(row.get("sell_back_price_jpy_per_kwh", "0"))
        except (ValueError, TypeError):
            continue
        tariff_map.setdefault(sid, []).append((sh, eh, price, sell))

    prices: List[ElectricityPrice] = []
    for t_idx in range(num_periods):
        current_hour = start_hour + t_idx * (delta_t_min / 60.0)
        for sid in site_ids:
            bands = tariff_map.get(sid, [])
            ep = 20.0  # default price
            sp = 0.0
            for sh, eh, price, sell in bands:
                if sh <= current_hour < eh:
                    ep = price
                    sp = sell
                    break
            # fallback: "*" (全サイト共通)
            if not bands:
                for sh, eh, price, sell in tariff_map.get("*", []):
                    if sh <= current_hour < eh:
                        ep = price
                        sp = sell
                        break

            prices.append(ElectricityPrice(
                site_id=sid,
                time_idx=t_idx,
                grid_energy_price=ep,
                sell_back_price=sp,
                base_load_kw=base_load_kw,
            ))
    return prices


# ---------------------------------------------------------------------------
# 運賃制度 (Revenue Model)
# ---------------------------------------------------------------------------

def load_fare_table(
    csv_path: Path,
) -> List[Dict[str, str]]:
    """fare_table.csv を読み込む。

    CSV 形式:
        route_id, fare_type, base_fare_jpy, per_km_fare_jpy,
        zone_fare_jpy, max_fare_jpy, discount_pct_ic_card
    """
    if not csv_path.exists():
        return []
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def estimate_trip_revenue(
    trip: GeneratedTrip,
    fare_table: Dict[str, Dict[str, float]],
    passenger_load_factor: float = 0.5,
    vehicle_capacity: int = 70,
) -> float:
    """1 trip の推定運賃収入 [円] を計算する。

    Parameters
    ----------
    trip : GeneratedTrip
    fare_table : route_id → {fare_type, base_fare, per_km_fare, ...}
    passenger_load_factor : 乗車率
    vehicle_capacity : 車両定員

    Returns
    -------
    float : 推定収入 [円]
    """
    fare_info = fare_table.get(trip.route_id, {})
    fare_type = fare_info.get("fare_type", "flat")
    base_fare = fare_info.get("base_fare_jpy", 220.0)
    per_km = fare_info.get("per_km_fare_jpy", 0.0)
    discount = fare_info.get("discount_pct_ic_card", 0.0) / 100.0

    # 乗客数推定
    pax = vehicle_capacity * passenger_load_factor

    if fare_type == "flat":
        revenue = base_fare * pax
    elif fare_type == "distance":
        revenue = (base_fare + per_km * trip.distance_km) * pax
    elif fare_type == "zone":
        zone_fare = fare_info.get("zone_fare_jpy", 250.0)
        revenue = zone_fare * pax
    else:
        revenue = base_fare * pax

    # IC カード割引
    revenue *= (1.0 - discount * 0.3)  # 30% が IC カード利用と仮定
    return round(revenue, 0)


def compute_route_profitability(
    trips: List[GeneratedTrip],
    fare_table: Dict[str, Dict[str, float]],
    trip_load_factors: Dict[str, float],
    trip_costs: Dict[str, float],
    vehicle_capacity: int = 70,
) -> Dict[str, Dict[str, float]]:
    """路線ごとの採算性を計算する。

    Returns
    -------
    Dict[route_id, {total_revenue, total_cost, profit, profitability_ratio}]
    """
    route_revenue: Dict[str, float] = {}
    route_cost: Dict[str, float] = {}

    for trip in trips:
        rid = trip.route_id
        lf = trip_load_factors.get(trip.trip_id, 0.5)
        rev = estimate_trip_revenue(trip, fare_table, lf, vehicle_capacity)
        cost = trip_costs.get(trip.trip_id, 0.0)
        route_revenue[rid] = route_revenue.get(rid, 0.0) + rev
        route_cost[rid] = route_cost.get(rid, 0.0) + cost

    result: Dict[str, Dict[str, float]] = {}
    for rid in set(list(route_revenue.keys()) + list(route_cost.keys())):
        rev = route_revenue.get(rid, 0.0)
        cost = route_cost.get(rid, 0.0)
        result[rid] = {
            "total_revenue": round(rev, 0),
            "total_cost": round(cost, 0),
            "profit": round(rev - cost, 0),
            "profitability_ratio": round(rev / cost, 4) if cost > 0 else float("inf"),
        }
    return result
