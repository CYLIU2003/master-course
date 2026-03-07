"""
src.preprocess.timetable_generator — ダイヤ展開・発車時刻生成

spec_v3 §10.2 / §4.1
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from src.schemas.route_entities import TimetablePattern, ServiceCalendarRow


def _parse_time(time_str: str) -> datetime:
    """'HH:MM' → datetime (date=1900-01-01)"""
    return datetime.strptime(time_str, "%H:%M")


def _fmt_time(dt: datetime) -> str:
    """datetime → 'HH:MM'"""
    return dt.strftime("%H:%M")


def generate_departure_times(
    pattern: TimetablePattern,
    max_trips: int = 200,
) -> List[str]:
    """TimetablePattern の headway に基づいて発車時刻リストを生成する。

    Parameters
    ----------
    pattern : TimetablePattern
    max_trips : int
        安全上限（無限ループ防止）

    Returns
    -------
    List[str] : 'HH:MM' 形式の発車時刻リスト
    """
    start = _parse_time(pattern.start_time)
    end = _parse_time(pattern.end_time)

    # 翌日越えを考慮（終了時刻が開始より前 = 翌日）
    if end <= start:
        end += timedelta(days=1)

    interval = timedelta(minutes=pattern.headway_min)
    times: List[str] = []
    current = start
    count = 0
    while current <= end and count < max_trips:
        times.append(_fmt_time(current))
        current += interval
        count += 1

    return times


def expand_service_calendar(
    calendar_rows: List[ServiceCalendarRow],
    date_from: str,
    date_to: str,
) -> Dict[str, str]:
    """日付範囲内の日付 → service_day_type マッピングを返す。

    Parameters
    ----------
    calendar_rows : List[ServiceCalendarRow]
        明示的な日付ルール
    date_from : str  "YYYY-MM-DD"
    date_to   : str  "YYYY-MM-DD"

    Returns
    -------
    Dict[str, str] : date_str → service_day_type
        明示ルールにない日付は曜日で推定 (weekday/saturday/holiday)
    """
    explicit: Dict[str, str] = {
        row.date: row.service_day_type
        for row in calendar_rows
        if row.is_active
    }

    result: Dict[str, str] = {}
    current_date = datetime.strptime(date_from, "%Y-%m-%d")
    end_date = datetime.strptime(date_to, "%Y-%m-%d")

    while current_date <= end_date:
        ds = current_date.strftime("%Y-%m-%d")
        if ds in explicit:
            result[ds] = explicit[ds]
        else:
            wd = current_date.weekday()  # 0=Monday, 6=Sunday
            if wd == 5:
                result[ds] = "saturday"
            elif wd == 6:
                result[ds] = "holiday"
            else:
                result[ds] = "weekday"
        current_date += timedelta(days=1)

    return result
