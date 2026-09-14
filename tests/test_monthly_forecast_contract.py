from datetime import datetime, timedelta
import hashlib
import json

import pytest

from bff.services.date_series_inputs import _date_forecast_rows
from src.optimization.common.date_series import content_hash
from src.preprocess.weather.seasonal_forecast_proxy import predict_climatology_ghi
from src.preprocess.weather.solcast_archive import JST


def _holdout(tmp_path, change=None):
    directory = tmp_path / "monthly_forecasts"
    directory.mkdir()
    model = {"slot_minutes": 15, "training_end_exclusive": "2025-01-01",
             "latitude": 35.635, "longitude": 139.646,
             "cells": [{"season": "winter", "weather_class": "sunny",
                        "source_day_count": 20, "attenuation_by_slot": [.7] * 96}]}
    starts = [datetime(2025, 1, 6, tzinfo=JST) + timedelta(minutes=i*15) for i in range(672)]
    prediction = predict_climatology_ghi(model, starts, issued_at=starts[0])
    profile = {"week_start": "2025-01-06", "model_sha256": content_hash(model),
               "training_end_exclusive": "2025-01-01",
               "valid_starts": [stamp.isoformat() for stamp in starts],
               "ghi_w_m2": [row["ghi_w_m2"] for row in prediction]}
    if change == "values":
        profile["ghi_w_m2"][48] += 1
    elif change == "timestamp":
        profile["valid_starts"][0] = "2025-01-05T23:45:00+09:00"
    elif change == "model":
        profile["model_sha256"] = "different"
    documents = {"training_model.json": model, "2025-01-06_forecast.json": profile}
    for name, document in documents.items():
        (directory / name).write_text(json.dumps(document), encoding="utf-8")
    manifest = {"artifacts": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                              for name in documents},
                "design": {"evaluation_weeks": ["2025-01-06"], "training_end_exclusive": "2025-01-01"}}
    if change == "hash":
        manifest["artifacts"]["2025-01-06_forecast.json"] = "incorrect"
    if change == "undeclared":
        manifest["design"]["evaluation_weeks"] = []
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    dates = [(starts[0] + timedelta(days=i)).date().isoformat() for i in range(7)]
    return directory, dates


def test_explicit_campaign_profile_is_bound_to_planning_predictions(tmp_path):
    directory, dates = _holdout(tmp_path)
    profiles, audit = _date_forecast_rows(tmp_path, dates, 15, .85, forecast_directory=directory)
    assert len(profiles) == 7
    assert all(len(profile["capacity_factor_by_slot"]) == 96 for profile in profiles)
    assert audit["weekly_profile_verified"] is True
    assert audit["holdout_directory"] == "monthly_forecasts"
    assert len(audit["weekly_profile_sha256"]) == 64


@pytest.mark.parametrize("change", ["values", "timestamp", "model", "hash", "undeclared"])
def test_inconsistent_weekly_forecast_is_rejected(tmp_path, change):
    directory, dates = _holdout(tmp_path, change)
    with pytest.raises(ValueError, match="weekly forecast"):
        _date_forecast_rows(tmp_path, dates, 15, .85, forecast_directory=directory)
