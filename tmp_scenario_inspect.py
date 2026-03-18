import json, urllib.request
sid='bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f'
u=f'http://127.0.0.1:8766/api/scenarios/{sid}'
print(urllib.request.urlopen(u,timeout=20).status)
d=json.loads(urllib.request.urlopen(u,timeout=20).read().decode('utf-8'))
print('keys', list(d.keys())[:20])
print('dispatchScope', d.get('dispatchScope'))
