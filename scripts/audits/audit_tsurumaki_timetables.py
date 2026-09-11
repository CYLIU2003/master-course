"""Compare fixed-version ODPT trips with captured official full-stop tables.

The output is a new, versioned input candidate. Parent scenarios and frozen
research evidence are read only; a geographic distance proxy is explicit.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata
from urllib.parse import parse_qs, urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bff.services.run_preparation import _route_stop_polyline_distance_km
from src.service_day_types import normalize_service_day_type, SERVICE_ID_BY_DAY_TYPE


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_key(value: str) -> str:
    return ''.join(unicodedata.normalize('NFKC', value).split())


class DiagramLinks(HTMLParser):
    """Read the actual weekday/Saturday/holiday columns, not URL weekdays."""

    def __init__(self):
        super().__init__()
        self.day_type = None
        self.links = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'td':
            self.day_type = {'wkd':'weekday','std':'saturday','snd':'sunday_or_holiday'}.get(attrs.get('class'))
        if tag == 'a' and self.day_type and 'BusRouteTimetable?' in attrs.get('href',''):
            self.links.append((attrs['href'], self.day_type))

    def handle_endtag(self, tag):
        if tag == 'td':
            self.day_type = None


def parse_browser_stops(page: dict) -> list[dict]:
    pattern = r'^(\d{2}:\d{2})(発|着)\s+\d+じ\d+ふん(?:発|着)\s+(.+?)(?:\s+\[時刻表\])?$'
    stops = [{'time': match[1], 'event':match[2], 'name':match[3].strip()}
             for line in page['text'].splitlines() if (match := re.match(pattern, line.strip()))]
    if len(stops) < 2 or stops[0]['event'] != '発' or any(row['event'] != '着' for row in stops[1:]):
        raise ValueError(f'Unrecognized full-stop timetable: {page["url"]}')
    return stops


def browser_index(directory: Path) -> tuple[dict, list]:
    declared_days, sources = {}, []
    for path in sorted(directory.glob('*_diagram*.json')):
        page = read_json(path)
        if hashlib.sha256(page['html'].encode()).hexdigest() != page['html_sha256']:
            raise ValueError(f'Browser source hash mismatch: {path.name}')
        parser = DiagramLinks()
        parser.feed(page['html'])
        for href, day_type in parser.links:
            url = urljoin(page['url'], href)
            if url in declared_days and declared_days[url] != day_type:
                raise ValueError('Conflicting service days in official columns')
            declared_days[url] = day_type
        sources.append({'path':path.as_posix(), 'sha256':digest(path), 'url':page['url']})
    index = defaultdict(list)
    for path in sorted(directory.glob('trip_*.json')):
        page = read_json(path)
        if hashlib.sha256(page['html'].encode()).hexdigest() != page['html_sha256']:
            raise ValueError(f'Browser source hash mismatch: {path.name}')
        day_type = declared_days.get(page['url'])
        if not day_type:
            raise ValueError(f'Full-stop page has no known source calendar: {path.name}')
        stops = parse_browser_stops(page)
        key = (day_type, stops[0]['time'], tuple(text_key(row['name']) for row in stops))
        index[key].append({'url':page['url'], 'path':path.as_posix(), 'stops':stops, 'sha256':digest(path)})
        sources.append({'path':path.as_posix(), 'sha256':digest(path), 'url':page['url']})
    return index, sources


def load_odpt_sources(directory: Path) -> tuple[dict, dict, dict]:
    manifest = read_json(directory/'acquisition_manifest.json')
    grouped, provenance = defaultdict(list), {}
    for source in manifest['sources']:
        path = Path(source['path'])
        if digest(path) != source['sha256']:
            raise ValueError(f'ODPT source hash mismatch: {path.name}')
        resource = source['request']['endpoint'].rsplit('/',1)[-1]
        rows = read_json(path)
        grouped[resource].extend(rows)
        for row in rows:
            provenance[row['owl:sameAs']] = {'path':path.as_posix(), 'sha256':source['sha256'], 'dc_date':row.get('dc:date')}
    return manifest, grouped, provenance


def time_minutes(value: str) -> int:
    match = re.fullmatch(r'(\d{1,2}):(\d{2})', value)
    if not match or int(match[2]) >= 60 or int(match[1]) >= 48:
        raise ValueError(f'Invalid service time: {value!r}')
    return int(match[1])*60+int(match[2])


def compare_parent_scenarios(trip_rows: list[dict]) -> dict:
    current = {row['trip_id']:row for row in trip_rows}
    result = {}
    for role,scenario_id in [('SUNNY','771d115b-75b0-49f7-a7f0-25f259a2cd21'),('RAIN','b23fd26c-1233-4c73-bb9e-bdb8b1584760')]:
        directory = Path('output/scenarios')/scenario_id
        path = directory/'artifacts.sqlite'
        with sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True) as connection:
            rows = [json.loads(row[0]) for row in connection.execute('SELECT payload_json FROM timetable_rows ORDER BY row_index')]
        changed = []
        for row in rows:
            new = current.get(row['trip_id'])
            if new:
                differences={key:{'parent':row.get(key),'current':new.get(key)} for key in ('departure','arrival','origin','destination') if row.get(key)!=new.get(key)}
                if differences:
                    changed.append({'trip_id':row['trip_id'],'differences':differences})
        result[role] = {'scenario_id':scenario_id,'timetable_count':len(rows),
                        'service_counts':dict(Counter(row.get('service_id') for row in rows)),
                        'route_ids':sorted({row['route_id'] for row in rows}),
                        'nonpositive_or_missing_distance_count':sum(float(row.get('distance_km') or 0)<=0 for row in rows),
                        'missing_explicit_operator_in_row_count':sum(not row.get('operator_id') for row in rows),
                        'trip_ids_absent_from_current':sorted(row['trip_id'] for row in rows if row['trip_id'] not in current),
                        'changed_endpoint_times_or_names':changed,
                        'source_files':{p.as_posix():digest(p) for p in (Path(str(directory)+'.json'),path,directory/'master_data.sqlite')},
                        'interpretation':'Materialized scenario comparison. Missing row-level operator is reported; ODPT operator provenance is resolved separately.'}
    return result


def audit(odpt_dir: Path, browser_dir: Path, output: Path) -> dict:
    manifest, raw, provenance = load_odpt_sources(odpt_dir)
    index, browser_sources = browser_index(browser_dir)
    route_catalog = Path('data/catalog-fast/normalized/routes.jsonl')
    routes = [json.loads(line) for line in route_catalog.read_text(encoding='utf-8').splitlines()]
    selected_routes = [row for row in routes if row['id'] in manifest['original_route_ids']]
    route_by_pattern = {row['odptPatternId']:row for row in selected_routes}
    stops = {row['owl:sameAs']:row for row in raw['odpt:BusstopPole']}
    coordinates = {key:(float(row['geo:lat']),float(row['geo:long'])) for key,row in stops.items()
                   if row.get('geo:lat') is not None and row.get('geo:long') is not None}
    if any(not all(math.isfinite(x) for x in point) or not (-90<=point[0]<=90 and -180<=point[1]<=180) for point in coordinates.values()):
        raise ValueError('Invalid official stop coordinates')
    current = [row for row in raw['odpt:BusTimetable'] if row['odpt:busroutePattern'] in route_by_pattern]
    ids = [row['owl:sameAs'] for row in current]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate ODPT trip identifiers')
    comparisons, trip_rows, sequence_rows, used_stops = [], [], [], set()
    for trip in sorted(current, key=lambda row:row['owl:sameAs']):
        route = route_by_pattern[trip['odpt:busroutePattern']]
        day_type = normalize_service_day_type(trip.get('odpt:calendar'))
        if day_type not in ('weekday','saturday','sunday_or_holiday') or trip.get('odpt:operator') != 'odpt.Operator:TokyuBus':
            raise ValueError('Unknown calendar or operator in official trip')
        # Input order is a contract; a broken index is exposed, never sorted away.
        schedule = trip['odpt:busTimetableObject']
        if [row['odpt:index'] for row in schedule] != list(range(1,len(schedule)+1)):
            raise ValueError('Nonconsecutive official stop sequence')
        stop_ids = tuple(row['odpt:busstopPole'] for row in schedule)
        names = tuple(text_key(stops[key]['dc:title']) for key in stop_ids)
        times = [row.get('odpt:departureTime') if i==0 else row.get('odpt:arrivalTime') for i,row in enumerate(schedule)]
        minutes = [time_minutes(value) for value in times]
        if any(b < a for a,b in zip(minutes,minutes[1:])):
            raise ValueError('Official trip times decrease; midnight semantics need explicit resolution')
        candidates = index.get((day_type,times[0],names), [])
        matching = [candidate for candidate in candidates if [row['time'] for row in candidate['stops']] == times]
        comparison = {'trip_id':trip['owl:sameAs'], 'route_id':route['id'], 'day_type':day_type,
                      'departure':times[0], 'arrival':times[-1], 'stop_count':len(stop_ids),
                      'status':'FULL_STOP_TIMES_MATCH' if matching else 'TIME_MISMATCH' if candidates else 'BROWSER_MATCH_MISSING',
                      'browser_sources':[{key:candidate[key] for key in ('url','path','sha256')} for candidate in (matching or candidates)],
                      'odpt_source':provenance[trip['owl:sameAs']]}
        if candidates and not matching:
            comparison['time_differences'] = [{'stop_index':i+1, 'name':names[i], 'odpt':a, 'browser':b['time']}
                                               for i,(a,b) in enumerate(zip(times,candidates[0]['stops'])) if a!=b['time']]
        distance, segments = _route_stop_polyline_distance_km(stop_ids,coordinates)
        if distance <= 0 or segments != len(stop_ids)-1:
            raise ValueError('Missing geographic distance evidence for '+trip['owl:sameAs'])
        comparisons.append(comparison)
        trip_rows.append({'trip_id':trip['owl:sameAs'], 'route_id':route['id'], 'operator_id':'tokyu',
                          'odpt_operator_id':trip['odpt:operator'], 'service_id':SERVICE_ID_BY_DAY_TYPE[day_type],
                          'day_type':day_type, 'direction':route['direction'], 'routeCode':route['routeCode'],
                          'origin':stops[stop_ids[0]]['dc:title'], 'destination':stops[stop_ids[-1]]['dc:title'],
                          'origin_stop_id':stop_ids[0], 'destination_stop_id':stop_ids[-1],
                          'departure':times[0], 'arrival':times[-1], 'runtime_min':minutes[-1]-minutes[0],
                          'distance_km':round(distance,6), 'distance_source':'trip_stop_sequence_polyline_haversine',
                          'distance_stop_count':len(stop_ids), 'distance_segment_count':segments,
                          'allowed_vehicle_types':['BEV','ICE'], 'odptPatternId':trip['odpt:busroutePattern'],
                          'odptTimetableId':trip['owl:sameAs'], 'source':'odpt_current_20260901',
                          'source_provenance':provenance[trip['owl:sameAs']], 'browser_verification':comparison['status']})
        sequence_rows.extend({'trip_id':trip['owl:sameAs'],'stop_sequence':i+1,'stop_id':stop_id,
                              'arrival_time':schedule[i].get('odpt:arrivalTime'),
                              'departure_time':schedule[i].get('odpt:departureTime')}
                             for i,stop_id in enumerate(stop_ids))
        used_stops.update(stop_ids)
    previous_path = Path('data/catalog-fast/raw/bus_timetable.ndjson')
    old = {row['owl:sameAs']:row for line in previous_path.read_text(encoding='utf-8').splitlines()
           if (row:=json.loads(line)).get('odpt:busroutePattern') in route_by_pattern}
    latest = {row['owl:sameAs']:row for row in current}
    changed = [key for key in sorted(old.keys() & latest.keys()) if old[key]['odpt:busTimetableObject'] != latest[key]['odpt:busTimetableObject']]
    counts = Counter(row['status'] for row in comparisons)
    stop_rows = [{'id':key,'name':stops[key]['dc:title'],'lat':coordinates[key][0],'lon':coordinates[key][1],
                  'operator_id':'tokyu','source_provenance':provenance[key]} for key in sorted(used_stops)]
    output.mkdir(parents=True, exist_ok=True)
    for name,payload in [('timetable_rows.json',trip_rows),('stop_sequences.json',sequence_rows),('stops.json',stop_rows),
                         ('selected_routes.json',selected_routes),('full_stop_comparison.json',comparisons)]:
        (output/name).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    by_route_day = Counter((row['route_id'],row['service_id']) for row in trip_rows)
    with (output/'route_day_counts.csv').open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['route_id','name','WEEKDAY','SAT','SUN_HOL'])
        writer.writeheader()
        writer.writerows({'route_id':row['id'],'name':row['name'],**{day:by_route_day[row['id'],day] for day in ('WEEKDAY','SAT','SUN_HOL')}} for row in selected_routes)
    result = {'schema_version':'tsurumaki_fixed_timetable_audit_v1',
              'status':'TIMETABLE_VERIFIED_DISTANCE_PROXY_DECLARED' if counts['FULL_STOP_TIMES_MATCH']==len(current) else 'BLOCKED_BROWSER_COMPARISON',
              'trip_count':len(trip_rows),'service_counts':dict(Counter(row['service_id'] for row in trip_rows)),
              'comparison_counts':dict(counts), 'source_version':'ODPT dc:date 2026-09-01; official website captured 2026-09-10',
              'sources':manifest['sources'], 'browser_sources':browser_sources,
              'parent_scenarios':compare_parent_scenarios(trip_rows),
              'old_raw_comparison':{'path':previous_path.as_posix(),'sha256':digest(previous_path),'old_trip_count':len(old),
                                    'status':'COMPARABLE' if old else 'NO_MATCHING_RAW_TRIPS_NOT_A_SERVICE_CHANGE',
                                    'added_trip_ids':sorted(latest.keys()-old.keys()) if old else [],'removed_trip_ids':sorted(old.keys()-latest.keys()),
                                    'changed_full_stop_sequence_or_times':changed},
              'excluded_additional_patterns':manifest['current_additional_patterns_for_same_route_codes'],
              'distance_semantics':'Sum of adjacent official stop coordinate haversine segments; geographic proxy, not measured road-network distance.',
              'operator_unknown_count':0, 'limits':['Fixed version applied to date-specific service calendars; not 2025 actual operations.',
                                                  'Parent scenario timetable_rows remain unchanged.',
                                                  'This verifies source input; it does not pass solver, rolling, physical, or research acceptance.'],
              'artifacts':{path.name:{'sha256':digest(path),'bytes':path.stat().st_size} for path in output.iterdir() if path.is_file() and path.name!='manifest.json'}}
    (output/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--odpt-dir',type=Path,required=True)
    parser.add_argument('--browser-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=audit(args.odpt_dir,args.browser_dir,args.output)
    print(json.dumps({key:result[key] for key in ('status','trip_count','service_counts','comparison_counts')},ensure_ascii=False))


if __name__=='__main__':
    main()
