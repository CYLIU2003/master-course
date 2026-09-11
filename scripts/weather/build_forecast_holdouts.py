"""Create immutable training-only climatology and calendar-selected test weeks."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from scripts.weather.build_seasonal_archive import write_csv, write_json
from src.optimization.common.date_series import content_hash
from src.preprocess.weather.seasonal_forecast_proxy import fit_climatology_proxy, predict_climatology_ghi
from src.preprocess.weather.solcast_archive import JST, load_verified_archive, parse_timestamp


def build(root: Path, output: Path, *, design_path: Path | None = None,
          reference_path: Path | None = None) -> dict:
    design_path = design_path or root/'config/seven_day_evaluation.json'
    design=json.loads(design_path.read_text(encoding='utf-8'))
    reference_path = reference_path or root/'data/derived/seasonal_irradiance/tsurumaki/training_cy2024/seasonal_curves.json'
    reference=json.loads(reference_path.read_text(encoding='utf-8'))
    raw=root/'data/external/solcast_raw/tsurumaki_2025_2026'
    records,sources=load_verified_archive(raw,date.fromisoformat(design['training_start']),date.fromisoformat(design['training_end_exclusive']))
    model=fit_climatology_proxy(records,reference,latitude=35.63514694444444,longitude=139.6462427777778)
    model['source_sha256']=[row['sha256'] for row in sources]
    model['reference_sha256']=hashlib.sha256(reference_path.read_bytes()).hexdigest()
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/'training_model.json',model)
    summaries=[]
    for week in design['evaluation_weeks']:
        beginning=date.fromisoformat(week)
        actual,actual_sources=load_verified_archive(raw,beginning,beginning+timedelta(days=7))
        start=datetime.combine(beginning,datetime.min.time(),JST)
        stamps=[start+timedelta(minutes=i*15) for i in range(672)]
        prediction=predict_climatology_ghi(model,stamps,issued_at=start)
        for index,(row,pred) in enumerate(zip(actual,prediction)):
            if parse_timestamp(row['period_end'])!=stamps[index]+timedelta(minutes=15):
                raise ValueError('Forecast/actual interval mismatch')
            pred.update(actual_ghi_w_m2=float(row['ghi']),residual_w_m2=float(row['ghi'])-pred['ghi_w_m2'])
        values=[row['ghi_w_m2'] for row in prediction]
        profile={'week_start':week,'source_kind':'training_only_climatology_proxy','model_sha256':content_hash(model),
                 'training_end_exclusive':model['training_end_exclusive'],'valid_starts':[stamp.isoformat() for stamp in stamps],
                 'ghi_w_m2':values,'profile_sha256':content_hash(values),
                 'issue_schedule':[{'decision_at':(start+timedelta(hours=i)).isoformat(),'start_slot':i*4,
                                    'available_stop_slot':672,'forecast_profile_sha256':content_hash(values)} for i in range(168)],
                 'issue_semantics':'Same training-only climatology reissued hourly; no claimed information improvement'}
        write_json(output/f'{week}_forecast.json',profile)
        write_csv(output/f'{week}_forecast_vs_actual.csv',prediction)
        daylight=[row for row in prediction if row['clear_ghi_w_m2']>=20]
        summary={'week_start':week,'interval_count':len(prediction),'daylight_interval_count':len(daylight),
                 'forecast_kind':'training_only_climatology_proxy','training_overlap_days':[],
                 'mae_daylight_w_m2':sum(abs(row['residual_w_m2']) for row in daylight)/len(daylight),
                 'rmse_daylight_w_m2':(sum(row['residual_w_m2']**2 for row in daylight)/len(daylight))**.5,
                 'actual_irradiation_kwh_m2':sum(row['actual_ghi_w_m2'] for row in prediction)*.25/1000,
                 'proxy_irradiation_kwh_m2':sum(values)*.25/1000,
                 'actual_source_sha256':[source['sha256'] for source in actual_sources]}
        summaries.append(summary)
    write_json(output/'evaluation_summary.json',{'status':'PROXY_EVALUATION_NOT_SOLCAST_FORECAST_SKILL','weeks':summaries})
    manifest={'schema_version':'forecast_holdouts_v1','status':'TRAINING_AND_TEST_SEPARATED',
              'design':design,'model_sha256':content_hash(model),'artifacts':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(output.iterdir()) if p.is_file() and p.name!='manifest.json'},
              'implementation_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                [Path(__file__).resolve(),root/'src/preprocess/weather/seasonal_forecast_proxy.py']}}
    write_json(output/'manifest.json',manifest)
    return {'status':manifest['status'],'weeks':len(summaries),'model_source_day_count':len(model['training_source_dates'])}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('data/derived/seasonal_irradiance/tsurumaki/forecast_holdouts'))
    parser.add_argument('--design',type=Path)
    parser.add_argument('--reference',type=Path)
    args=parser.parse_args()
    print(json.dumps(build(Path(__file__).resolve().parents[2],args.output,
                          design_path=args.design,reference_path=args.reference),ensure_ascii=False))
