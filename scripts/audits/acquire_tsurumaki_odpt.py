"""Capture current official ODPT sources for the declared Tsurumaki scope.

Raw responses and sanitized requests are preserved separately from scenarios.
Nothing in this command rewrites timetable rows or invents stop times/distances.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.catalog._odpt_runtime import resolve_odpt_api_key
from scripts.catalog.build_tokyu_subset_db import ODPT_BASE, OPERATOR_ID, normalize_route_code
from scripts.run_frontend_controlled_pv_pair import TARGET_ROUTE_IDS_BY_DEPOT


def capture_resource(output: Path, resource: str, params: dict, key: str) -> tuple[list, dict]:
    """Preserve server bytes; never persist credentials or exception URLs."""
    request_info = {'endpoint': f'{ODPT_BASE}/{resource}', 'query': params}
    request_hash = hashlib.sha256(json.dumps(request_info, sort_keys=True).encode()).hexdigest()
    stem = resource.replace(':', '_')+'_'+request_hash[:16]
    raw_path, manifest_path = output / (stem+'.json'), output / (stem+'.manifest.json')
    if raw_path.exists() or manifest_path.exists():
        metadata = json.loads(manifest_path.read_text(encoding='utf-8'))
        raw = raw_path.read_bytes()
        if metadata['request'] != request_info or hashlib.sha256(raw).hexdigest() != metadata['sha256']:
            raise ValueError(f'Existing source provenance mismatch: {stem}')
    else:
        url = request_info['endpoint']+'?'+urlencode({**params, 'acl:consumerKey': key})
        req = Request(url, headers={'Accept':'application/json', 'User-Agent':'master-course-tsurumaki-audit/1.0'})
        try:
            with urlopen(req, timeout=90) as response:
                raw = response.read()
        except HTTPError as exc:
            raise RuntimeError(f'ODPT {resource} HTTP {exc.code}; no synthetic fallback') from None
        except (URLError, TimeoutError):
            raise RuntimeError(f'ODPT {resource} network failure; source is unresolved') from None
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ValueError(f'ODPT {resource} did not return an array')
        metadata = {'request':request_info, 'sha256':hashlib.sha256(raw).hexdigest(),
                    'retrieved_at_utc':datetime.now(timezone.utc).isoformat(), 'record_count':len(rows),
                    'path':raw_path.as_posix(), 'data_kind':'official_current_scheduled_service_not_historical_actual_operations'}
        raw_path.write_bytes(raw)
        manifest_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        time.sleep(.5)
    rows = json.loads(raw)
    if len(rows) != metadata['record_count']:
        raise ValueError('Stored ODPT record count mismatch')
    print(f'{resource}: {len(rows)} records', flush=True)
    return rows, metadata


def acquire(output: Path) -> dict:
    key = resolve_odpt_api_key(None)
    output.mkdir(parents=True, exist_ok=True)
    catalog = Path('data/catalog-fast/normalized/routes.jsonl')
    selected_ids = set(TARGET_ROUTE_IDS_BY_DEPOT['tsurumaki'])
    original = [json.loads(line) for line in catalog.read_text(encoding='utf-8').splitlines() if line.strip()]
    selected = [row for row in original if row['id'] in selected_ids]
    if len(selected) != len(selected_ids):
        raise ValueError('Original 16-route scope could not be resolved exactly')
    patterns, pattern_source = capture_resource(output, 'odpt:BusroutePattern', {'odpt:operator':OPERATOR_ID}, key)
    route_codes = {'渋21','渋22','渋23'}
    relevant = [row for row in patterns if normalize_route_code(row.get('dc:title','')) in route_codes]
    if not relevant:
        raise ValueError('Current ODPT patterns did not contain the declared route codes')
    sources, timetables = [pattern_source], []
    for pattern in relevant:
        pattern_id = pattern['owl:sameAs']
        if pattern.get('odpt:operator') != OPERATOR_ID:
            raise ValueError('Unexpected operator in the selected ODPT patterns')
        rows, source = capture_resource(output, 'odpt:BusTimetable', {'odpt:busroutePattern':pattern_id}, key)
        if any(row.get('odpt:operator') != OPERATOR_ID or row.get('odpt:busroutePattern') != pattern_id for row in rows):
            raise ValueError('ODPT timetable operator/pattern does not match the request')
        sources.append(source)
        timetables.extend(rows)
    stops, stop_source = capture_resource(output, 'odpt:BusstopPole', {'odpt:operator':OPERATOR_ID}, key)
    sources.append(stop_source)
    old_patterns = {row['odptPatternId'] for row in selected}
    new_patterns = {row['owl:sameAs'] for row in relevant}
    result = {'schema_version':'tsurumaki_odpt_source_capture_v1', 'status':'SOURCES_CAPTURED_COMPARISON_PENDING',
              'original_route_ids':sorted(selected_ids), 'original_route_catalog_sha256':hashlib.sha256(catalog.read_bytes()).hexdigest(),
              'original_patterns':sorted(old_patterns), 'current_patterns':sorted(new_patterns),
              'original_patterns_absent_from_current':sorted(old_patterns-new_patterns),
              'current_additional_patterns_for_same_route_codes':sorted(new_patterns-old_patterns),
              'timetable_count':len(timetables), 'pattern_count':len(relevant), 'sources':sources,
              'source_dc_dates':sorted({row.get('dc:date','') for row in timetables}),
              'operator_ids':sorted({row.get('odpt:operator','') for row in timetables}),
              'calendars':{calendar:sum(row.get('odpt:calendar')==calendar for row in timetables)
                           for calendar in sorted({row.get('odpt:calendar','') for row in timetables})},
              'limits':['Current fixed timetable version; not a reconstruction of 2025 operations.',
                        'Additional route-code variants are captured for comparison and do not silently expand the selected scope.']}
    (output/'acquisition_manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = acquire(args.output)
    print(json.dumps({key:result[key] for key in ('status','pattern_count','timetable_count','calendars')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
