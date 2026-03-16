from bff.store import scenario_store
import json
import unicodedata

scenarios = scenario_store.list_scenarios()
s_id = scenarios[-1]['id']
scenario = scenario_store.get_scenario_document_shallow(s_id)
rows = scenario_store.get_field(s_id, 'timetable_rows') or []

target_names = ['東98', '渋41', '黒01', '黒02']
route_map = {}
for r in scenario.get('routes', []):
    name = r.get('displayName') or r.get('routeCode') or r.get('name') or ''
    norm_name = unicodedata.normalize('NFKC', name)
    for t in target_names:
        if t in norm_name:
            route_map[r['id']] = t

counts = {t: 0 for t in target_names}
for row in rows:
    if row.get('service_id') != 'WEEKDAY': continue
    rid = row.get('route_id')
    if rid in route_map:
        counts[route_map[rid]] += 1

# write to file to avoid encoding issues on print
with open('counts.json', 'w', encoding='utf-8') as f:
    json.dump(counts, f, ensure_ascii=False)
