import pandas as pd
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')
df = pd.read_parquet('outputs/scenarios/fac6a4e0-e6ff-45d2-9246-17230e4b383f/trip_set.parquet')
trips = [json.loads(p) for p in df['payload_json']]

from collections import Counter
counts = Counter()

for t in trips:
    r_id = t.get('route_id')
    counts[r_id] += 1

print(f"Total trips: {len(trips)}")
for k, v in counts.items():
    print(f"{k}: {v}便")
