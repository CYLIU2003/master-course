import json
import sys
import glob

# Try to find the catalog file for Tokyu bus
catalog_files = glob.glob("data/tokyubus/canonical/*/routes.jsonl")
if not catalog_files:
    print("No route files found")
    sys.exit(0)

print(f"Reading from {catalog_files[-1]}")
with open(catalog_files[-1], "r", encoding="utf-8") as f:
    for line in f:
        route = json.loads(line)
        # Just print ones that might be meguro related or have trip counts
        # Actually trip counts are usually in trips.jsonl or stop_timetables
        pass

