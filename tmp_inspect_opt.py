import json,urllib.request
BASE='http://127.0.0.1:8771/api'
SID='bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f'
opt=json.loads(urllib.request.urlopen(f'{BASE}/scenarios/{SID}/optimization',timeout=60).read().decode('utf-8'))
print('top keys',list(opt.keys()))
print('solver_result type',type(opt.get('solver_result')).__name__)
print('solver_result keys',list((opt.get('solver_result') or {}).keys())[:40])
print('status',opt.get('status'))
print('objective top',opt.get('objective_value'))
print('solver_metadata', (opt.get('solver_result') or {}).get('solver_metadata'))
