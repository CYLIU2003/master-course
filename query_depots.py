import json
import glob

files = glob.glob("data/tokyubus/canonical/*/stops.jsonl")
if files:
    with open(files[-1], "r", encoding="utf-8") as f:
        for line in f:
            if "営業所" in line and "水道局" not in line:
                d = json.loads(line)
                print(d.get("stop_name"), d.get("stop_id"))

