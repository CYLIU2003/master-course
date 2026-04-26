import pytest

from src.preprocess.weather.kishojin_diary_parser import (
    KishojinParseError,
    parse_kishojin_diary_html,
)


def test_parse_kishojin_diary_html_extracts_daily_weather_rows():
    html = """
    <table>
      <tr><th>日</th><th>天気</th><th>最高</th><th>最低</th></tr>
      <tr><td>1</td><td>晴れ</td><td>33.2</td><td>25.1</td></tr>
      <tr><td>2</td><td>曇り時々雨</td><td>29.0</td><td>22.0</td></tr>
    </table>
    """

    rows = parse_kishojin_diary_html(
        html,
        year=2025,
        month=8,
        station_id="44132",
        station_name="東京",
    )

    assert [row.date for row in rows] == ["2025-08-01", "2025-08-02"]
    assert rows[0].weather_label == "晴れ"
    assert rows[0].tmax_c == 33.2
    assert rows[1].quality_flag == "ok"


def test_parse_kishojin_diary_html_marks_missing_cells_partial():
    html = """
    <table>
      <tr><td>1</td><td>曇り</td><td></td><td>24.0</td></tr>
    </table>
    """

    rows = parse_kishojin_diary_html(
        html,
        year=2025,
        month=8,
        station_id="44132",
        station_name="東京",
    )

    assert rows[0].quality_flag == "partial"
    assert rows[0].weather_label == "曇り"


def test_parse_kishojin_diary_html_rejects_unparseable_html():
    with pytest.raises(KishojinParseError):
        parse_kishojin_diary_html(
            "<html><body>not a diary table</body></html>",
            year=2025,
            month=8,
            station_id="44132",
            station_name="東京",
        )
