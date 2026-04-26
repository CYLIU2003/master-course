"""Parse locally saved Kishojin diary HTML into daily weather observations."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Any, List, Optional

from .daily_weather_schema import DailyWeatherObservation


class KishojinParseError(ValueError):
    """Raised when a Kishojin diary page cannot be parsed reliably."""


class _TableCellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: List[List[str]] = []
        self._current_row: Optional[List[str]] = None
        self._current_cell: Optional[List[str]] = None
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "tr":
            self._current_row = []
        elif tag.lower() in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            self._in_cell = True

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in {"td", "th"} and self._current_cell is not None:
            cell = " ".join(part.strip() for part in self._current_cell if part.strip())
            if self._current_row is not None:
                self._current_row.append(re.sub(r"\s+", " ", cell).strip())
            self._current_cell = None
            self._in_cell = False
        elif tag_name == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_WEATHER_KEYWORDS = ("晴", "曇", "雨", "雪", "雷", "霧")


def _optional_float(text: Any) -> Optional[float]:
    if text is None:
        return None
    match = _NUMBER_RE.search(str(text).replace(",", ""))
    if not match:
        return None
    return float(match.group(0))


def _day_from_cell(text: str) -> Optional[int]:
    match = re.match(r"\s*(\d{1,2})\b", str(text or ""))
    if not match:
        return None
    day = int(match.group(1))
    if not 1 <= day <= 31:
        return None
    return day


def _weather_label_from_cells(cells: list[str]) -> Optional[str]:
    for cell in cells:
        text = str(cell or "").strip()
        if any(keyword in text for keyword in _WEATHER_KEYWORDS):
            return text
    return None


def _temperature_candidates(cells: list[str], weather_label: Optional[str]) -> list[float]:
    values: list[float] = []
    for cell in cells:
        text = str(cell or "")
        if weather_label and text.strip() == weather_label:
            continue
        parsed = _optional_float(text)
        if parsed is not None and -40.0 <= parsed <= 60.0:
            values.append(parsed)
    return values


def parse_kishojin_diary_html(
    html: str,
    *,
    year: int,
    month: int,
    station_id: str,
    station_name: str,
    source: str = "kishojin",
) -> List[DailyWeatherObservation]:
    parser = _TableCellParser()
    parser.feed(html)
    observations: List[DailyWeatherObservation] = []
    for cells in parser.rows:
        if not cells:
            continue
        day = _day_from_cell(cells[0])
        if day is None:
            continue
        weather_label = _weather_label_from_cells(cells[1:])
        numeric_values = _temperature_candidates(cells[1:], weather_label)
        tmax_c = numeric_values[0] if len(numeric_values) >= 1 else None
        tmin_c = numeric_values[1] if len(numeric_values) >= 2 else None
        quality_flag = "ok" if weather_label and tmax_c is not None and tmin_c is not None else "partial"
        observations.append(
            DailyWeatherObservation(
                date=f"{int(year):04d}-{int(month):02d}-{day:02d}",
                station_id=station_id,
                station_name=station_name,
                source=source,
                weather_label=weather_label,
                tmax_c=tmax_c,
                tmin_c=tmin_c,
                mean_temp_c=None,
                sunshine_hours=None,
                precipitation_mm=None,
                quality_flag=quality_flag,
            )
        )
    if not observations:
        raise KishojinParseError("No daily rows could be parsed from Kishojin diary HTML")
    return observations


def parse_kishojin_diary_file(
    path: str | Path,
    *,
    year: int,
    month: int,
    station_id: str,
    station_name: str,
    source: str = "kishojin",
) -> List[DailyWeatherObservation]:
    source_path = Path(path)
    html = ""
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8", "utf-8-sig", "cp932", "shift_jis"):
        try:
            html = source_path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    if not html:
        raise KishojinParseError(f"Unable to decode {source_path}: {last_error}")
    return parse_kishojin_diary_html(
        html,
        year=year,
        month=month,
        station_id=station_id,
        station_name=station_name,
        source=source,
    )
