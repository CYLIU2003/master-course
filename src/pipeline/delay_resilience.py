"""
src.pipeline.delay_resilience — 遅延耐性テスト

行路設定表に基づく運用では遅延が後続行路へ波及する。
ランダム遅延を付与し、行路単位の slack やデッドヘッド時間の十分性を評価する。
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.schemas.route_entities import GeneratedTrip
from src.schemas.duty_entities import VehicleDuty


@dataclass
class DelayEvent:
    """1 便の遅延イベント。"""
    trip_id: str
    original_arrival: str       # "HH:MM"
    delayed_arrival: str        # "HH:MM"
    delay_min: float            # [min]
    cause: str = "random"       # "random" | "traffic" | "passenger" | "incident"


@dataclass
class PropagationEffect:
    """遅延波及の影響。"""
    duty_id: str
    affected_trip_id: str
    cascaded_delay_min: float
    missed_connection: bool = False
    missed_charging: bool = False
    slack_remaining_min: float = 0.0
    description: str = ""


@dataclass
class DelayResilienceReport:
    """遅延耐性テスト結果。"""
    n_scenarios: int = 0
    n_delay_events: int = 0
    total_propagations: int = 0
    missed_connections: int = 0
    missed_charging_opportunities: int = 0
    avg_cascade_delay_min: float = 0.0
    max_cascade_delay_min: float = 0.0
    pct_duties_affected: float = 0.0
    events: List[DelayEvent] = field(default_factory=list)
    propagations: List[PropagationEffect] = field(default_factory=list)

    # --- 行路ごとのサマリ ---
    duty_slack_summary: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"=== 遅延耐性テスト結果 ===",
            f"シナリオ数: {self.n_scenarios}",
            f"遅延イベント数: {self.n_delay_events}",
            f"波及影響数: {self.total_propagations}",
            f"接続不能 (missed connection): {self.missed_connections} 回",
            f"充電機会逸失: {self.missed_charging_opportunities} 回",
            f"平均カスケード遅延: {self.avg_cascade_delay_min:.1f} min",
            f"最大カスケード遅延: {self.max_cascade_delay_min:.1f} min",
            f"影響を受けた行路割合: {self.pct_duties_affected:.1%}",
        ]
        return "\n".join(lines)


def _parse_time(s: str) -> datetime:
    return datetime.strptime(s, "%H:%M")


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def generate_delay_events(
    trips: List[GeneratedTrip],
    delay_probability: float = 0.15,
    delay_mean_min: float = 5.0,
    delay_std_min: float = 3.0,
    max_delay_min: float = 30.0,
    seed: int = 42,
) -> List[DelayEvent]:
    """トリップにランダム遅延を付与する。

    Parameters
    ----------
    trips : List[GeneratedTrip]
    delay_probability : 遅延発生確率
    delay_mean_min : 平均遅延 [min]
    delay_std_min : 標準偏差 [min]
    max_delay_min : 最大遅延 [min]
    seed : 乱数シード

    Returns
    -------
    List[DelayEvent]
    """
    rng = random.Random(seed)
    events: List[DelayEvent] = []

    for trip in trips:
        if trip.trip_category != "revenue":
            continue
        if rng.random() > delay_probability:
            continue

        delay = max(0.0, min(rng.gauss(delay_mean_min, delay_std_min), max_delay_min))
        if delay < 1.0:
            continue

        try:
            orig_arr = _parse_time(trip.arrival_time)
            delayed_arr = orig_arr + timedelta(minutes=delay)
        except ValueError:
            continue

        events.append(DelayEvent(
            trip_id=trip.trip_id,
            original_arrival=trip.arrival_time,
            delayed_arrival=_fmt_time(delayed_arr),
            delay_min=round(delay, 1),
            cause="random",
        ))

    return events


def simulate_delay_propagation(
    duties: List[VehicleDuty],
    trips: List[GeneratedTrip],
    delay_events: List[DelayEvent],
    turnaround_buffer_min: float = 5.0,
    min_charging_time_min: float = 10.0,
) -> List[PropagationEffect]:
    """遅延イベントの行路内波及をシミュレーションする。

    Parameters
    ----------
    duties : List[VehicleDuty]
    trips : List[GeneratedTrip]
    delay_events : List[DelayEvent]
    turnaround_buffer_min : ターンアラウンドバッファ [min]
    min_charging_time_min : 充電に必要な最小時間 [min]

    Returns
    -------
    List[PropagationEffect]
    """
    trip_lut = {t.trip_id: t for t in trips}
    delay_map = {e.trip_id: e for e in delay_events}

    propagations: List[PropagationEffect] = []

    for duty in duties:
        revenue_legs = [leg for leg in duty.legs if leg.leg_type == "revenue" and leg.trip_id]
        accumulated_delay = 0.0

        for i, leg in enumerate(revenue_legs):
            tid = leg.trip_id
            trip = trip_lut.get(tid)
            if trip is None:
                continue

            # この trip 自体の遅延
            event = delay_map.get(tid)
            if event:
                accumulated_delay = max(accumulated_delay, event.delay_min)

            if accumulated_delay <= 0:
                continue

            # 次の trip への波及
            if i + 1 < len(revenue_legs):
                next_leg = revenue_legs[i + 1]
                next_trip = trip_lut.get(next_leg.trip_id)
                if next_trip is None:
                    continue

                try:
                    arr_time = _parse_time(trip.arrival_time) + timedelta(minutes=accumulated_delay)
                    next_dep = _parse_time(next_trip.departure_time)
                    slack = (next_dep - arr_time).total_seconds() / 60.0
                except ValueError:
                    slack = 0.0

                missed = slack < turnaround_buffer_min
                missed_charge = slack < min_charging_time_min

                eff = PropagationEffect(
                    duty_id=duty.duty_id,
                    affected_trip_id=next_trip.trip_id,
                    cascaded_delay_min=round(accumulated_delay, 1),
                    missed_connection=missed,
                    missed_charging=missed_charge and not missed,
                    slack_remaining_min=round(max(0, slack), 1),
                    description=(
                        f"遅延{accumulated_delay:.0f}min → "
                        f"slack={slack:.0f}min "
                        f"{'(接続不能)' if missed else '(OK)'}"
                    ),
                )
                propagations.append(eff)

                # slack を超えた分は次に波及
                if missed:
                    accumulated_delay = max(0, turnaround_buffer_min - slack)
                else:
                    accumulated_delay = max(0, accumulated_delay - slack)

    return propagations


def run_delay_resilience_test(
    duties: List[VehicleDuty],
    trips: List[GeneratedTrip],
    n_scenarios: int = 20,
    delay_probability: float = 0.15,
    delay_mean_min: float = 5.0,
    seed: int = 42,
) -> DelayResilienceReport:
    """複数シナリオで遅延耐性をテストする。

    Parameters
    ----------
    duties : List[VehicleDuty]
    trips : List[GeneratedTrip]
    n_scenarios : シナリオ回数
    delay_probability : 遅延確率
    delay_mean_min : 平均遅延 [min]
    seed : 基底シード

    Returns
    -------
    DelayResilienceReport
    """
    report = DelayResilienceReport(n_scenarios=n_scenarios)
    all_cascade_delays: List[float] = []
    affected_duties: set = set()

    for s in range(n_scenarios):
        events = generate_delay_events(
            trips, delay_probability, delay_mean_min, seed=seed + s
        )
        report.n_delay_events += len(events)

        props = simulate_delay_propagation(duties, trips, events)
        report.total_propagations += len(props)

        for p in props:
            if p.missed_connection:
                report.missed_connections += 1
            if p.missed_charging:
                report.missed_charging_opportunities += 1
            all_cascade_delays.append(p.cascaded_delay_min)
            affected_duties.add(p.duty_id)

        report.events.extend(events)
        report.propagations.extend(props)

    if all_cascade_delays:
        report.avg_cascade_delay_min = round(
            sum(all_cascade_delays) / len(all_cascade_delays), 1
        )
        report.max_cascade_delay_min = round(max(all_cascade_delays), 1)

    if duties:
        report.pct_duties_affected = len(affected_duties) / len(duties)

    # 行路ごとの slack サマリ
    for duty in duties:
        trip_lut = {t.trip_id: t for t in trips}
        revenue_legs = [l for l in duty.legs if l.leg_type == "revenue" and l.trip_id]
        slacks: List[float] = []
        for i in range(len(revenue_legs) - 1):
            t1 = trip_lut.get(revenue_legs[i].trip_id)
            t2 = trip_lut.get(revenue_legs[i + 1].trip_id)
            if t1 and t2:
                try:
                    gap = (_parse_time(t2.departure_time) - _parse_time(t1.arrival_time)).total_seconds() / 60.0
                    slacks.append(gap)
                except ValueError:
                    pass
        if slacks:
            report.duty_slack_summary[duty.duty_id] = {
                "min_slack_min": round(min(slacks), 1),
                "avg_slack_min": round(sum(slacks) / len(slacks), 1),
                "max_slack_min": round(max(slacks), 1),
            }

    return report


def export_delay_report(
    report: DelayResilienceReport,
    output_path: Path,
) -> None:
    """遅延耐性レポートを Markdown で出力する。"""
    lines: List[str] = [
        "# 遅延耐性テストレポート\n",
        report.summary(),
        "",
        "\n## 行路別 Slack サマリ\n",
        "| 行路 ID | 最小 slack [min] | 平均 slack [min] | 最大 slack [min] |",
        "|---------|-----------------|-----------------|-----------------|",
    ]
    for did, stats in report.duty_slack_summary.items():
        lines.append(
            f"| {did} | {stats['min_slack_min']:.1f} | "
            f"{stats['avg_slack_min']:.1f} | {stats['max_slack_min']:.1f} |"
        )

    if report.propagations[:30]:
        lines.append("\n## 波及詳細（上位30件）\n")
        lines.append("| # | 行路 | 影響 Trip | 遅延 [min] | 接続不能 | 充電逸失 | slack [min] |")
        lines.append("|---|------|----------|-----------|---------|---------|------------|")
        for i, p in enumerate(report.propagations[:30], 1):
            lines.append(
                f"| {i} | {p.duty_id} | {p.affected_trip_id} | "
                f"{p.cascaded_delay_min:.0f} | {'YES' if p.missed_connection else '-'} | "
                f"{'YES' if p.missed_charging else '-'} | {p.slack_remaining_min:.0f} |"
            )

    lines.append("\n---\n*Generated by delay_resilience pipeline*\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[delay_resilience] → {output_path}")
