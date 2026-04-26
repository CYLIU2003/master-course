from pathlib import Path

from src.preprocess.weather.jma_daily_csv_loader import load_jma_daily_csv


def test_jma_daily_csv_loader_reads_utf8_bom_and_japanese_columns(tmp_path: Path):
    path = tmp_path / "tokyo_utf8.csv"
    path.write_text(
        "\ufeff年月日,最高気温(℃),最低気温(℃),平均気温(℃),日照時間(時間),降水量(mm)\n"
        "2025/08/21,33.2,25.1,28.4,5.8,0.0\n",
        encoding="utf-8",
    )

    rows = load_jma_daily_csv(path, station_id="44132", station_name="東京")

    assert rows[0].date == "2025-08-21"
    assert rows[0].tmax_c == 33.2
    assert rows[0].sunshine_hours == 5.8


def test_jma_daily_csv_loader_reads_shift_jis_and_missing_numbers(tmp_path: Path):
    path = tmp_path / "tokyo_sjis.csv"
    csv_text = (
        "年月日,地点番号,地点名,最高気温(℃),最低気温(℃),日照時間(時間),降水量(mm)\n"
        "2025-08-21,44132,東京,--,25.1,///,0.0\n"
    )
    path.write_bytes(csv_text.encode("cp932"))

    rows = load_jma_daily_csv(path)

    assert rows[0].station_id == "44132"
    assert rows[0].station_name == "東京"
    assert rows[0].tmax_c is None
    assert rows[0].sunshine_hours is None
    assert rows[0].precipitation_mm == 0.0
