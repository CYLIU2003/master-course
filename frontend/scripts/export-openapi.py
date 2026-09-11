"""Export the live BFF schema without starting services or touching scenarios."""

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
from bff.main import app

schema = app.openapi()
output = Path(__file__).resolve().parents[1] / "openapi.json"
output.write_text(
    json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
