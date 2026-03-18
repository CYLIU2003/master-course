import json, urllib.request, pprint
u='http://127.0.0.1:8766/api/scenarios'
d=json.loads(urllib.request.urlopen(u,timeout=20).read().decode('utf-8'))
items=d.get('items',[])
print(type(items[0]).__name__)
pprint.pp(items[0])
