import re

with open("test_script.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add unicodedata import
if "import unicodedata" not in content:
    content = content.replace("import sys", "import sys\nimport unicodedata")

# Fix string matching
old_match = """    name = r.get('displayName') or r.get('routeCode') or r.get('name')
    if name in ['東98', '渋41', '黒01', '黒02']:
        target_routes.append(r_id)"""

new_match = """    name = r.get('displayName') or r.get('routeCode') or r.get('name')
    normalized_name = unicodedata.normalize('NFKC', name)
    if any(target in normalized_name for target in ['東98', '渋41', '黒01', '黒02']):
        target_routes.append(r_id)"""

content = content.replace(old_match, new_match)

with open("test_script.py", "w", encoding="utf-8") as f:
    f.write(content)
