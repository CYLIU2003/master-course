from datetime import datetime, timedelta

import pytest

from src.preprocess.weather.seasonal_forecast_proxy import astronomical_clear_ghi, predict_climatology_ghi
from src.preprocess.weather.solcast_archive import JST


def _model():
    return {'training_end_exclusive':'2025-01-01','latitude':35.635,'longitude':139.646,'slot_minutes':15,
            'cells':[{'season':season,'weather_class':weather,'source_day_count':10,'attenuation_by_slot':[ratio]*96}
                     for season in ('spring','summer','autumn','winter')
                     for weather,ratio in [('sunny',1),('cloudy',.5),('rainy',.2)]]}


def test_target_day_solar_geometry_has_no_night_generation_and_changes_with_season():
    winter=datetime(2025,1,15,tzinfo=JST)
    summer=datetime(2025,7,15,tzinfo=JST)
    for midnight in (winter,summer):
        assert astronomical_clear_ghi(midnight,35.635,139.646)==0
        assert astronomical_clear_ghi(midnight+timedelta(hours=23),35.635,139.646)==0
    assert astronomical_clear_ghi(summer+timedelta(hours=12),35.635,139.646)>astronomical_clear_ghi(winter+timedelta(hours=12),35.635,139.646)


def test_regular_forecast_uses_training_class_weights_without_future_class():
    stamp=datetime(2025,8,4,12,tzinfo=JST)
    predicted=predict_climatology_ghi(_model(),[stamp],issued_at=stamp-timedelta(hours=24))[0]
    assert predicted['ghi_w_m2']==pytest.approx(predicted['clear_ghi_w_m2']*(1+.5+.2)/3)
    assert predicted['known_weather_class'] is None
    assert predicted['lead_minutes']==1440
    assert predicted['training_day_count']==30
    oracle=predict_climatology_ghi(_model(),[stamp],issued_at=stamp,known_weather_class='rainy')[0]
    assert oracle['source_kind']=='known_class_oracle_reference'


@pytest.mark.parametrize('issued,valid',[(datetime(2024,12,1,tzinfo=JST),datetime(2025,1,2,tzinfo=JST)),
                                       (datetime(2025,1,2,tzinfo=JST),datetime(2025,1,1,tzinfo=JST))])
def test_forecast_rejects_issuance_before_training_or_after_valid_time(issued,valid):
    with pytest.raises(ValueError,match='unavailable at issuance'):
        predict_climatology_ghi(_model(),[valid],issued_at=issued)
