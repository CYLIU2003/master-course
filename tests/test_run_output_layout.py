from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.run_output_layout import allocate_run_dir


def test_allocate_run_dir_uses_dated_root_and_collision_suffix(tmp_path: Path) -> None:
    timestamp = datetime(2026, 4, 11, 12, 34)

    first_run_dir = allocate_run_dir(tmp_path, "2026-04-11", timestamp=timestamp)
    second_run_dir = allocate_run_dir(tmp_path, "2026-04-11", timestamp=timestamp)

    assert first_run_dir == tmp_path / "2026-04-11" / "run_20260411_1234"
    assert second_run_dir == tmp_path / "2026-04-11" / "run_20260411_1234_02"
    assert first_run_dir.exists()
    assert second_run_dir.exists()