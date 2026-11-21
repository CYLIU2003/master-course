"""Convert 原稿_下書き_v1.md into ordered blocks for the IEEJ Word template (fill_template.ps1).

Blocks: {"kind": "heading"|"para"|"table"|"figure"|"refhead"|"ref", ...}. Runs inside a
paragraph are [text, flags] where flags contain "sup" (citation) or "hl" (placeholder 〔…〕).
Citations are renumbered in order of first appearance; the mapping is written to the output too.
"""
import json
import re
import sys
from pathlib import Path

ZEN = str.maketrans("0123456789", "０１２３４５６７８９")


def clean(text):
    text = text.replace("**", "")
    text = re.sub(r"\$([^$]+)\$", lambda m: m.group(1).replace("{,}", ",").replace("\\times", "×").replace(" ", ""), text)
    return text.replace("CO₂", "CO2").replace("CO2", "CO₂")


def runs(text, cite_map):
    out = []
    for part in re.split(r"(〔[^〕]*〕)", text):
        if not part:
            continue
        m = re.fullmatch(r"〔(\d+)〕", part)
        if m:
            old = int(m.group(1))
            cite_map.setdefault(old, len(cite_map) + 1)
            out.append([f"({cite_map[old]})", "sup"])
        elif part.startswith("〔"):
            out.append([part, "hl"])
        else:
            out.append([part, ""])
    return out


def main(md_path, out_path):
    lines = Path(md_path).read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("## 1."))
    end = next(i for i, l in enumerate(lines) if l.startswith("## 文献"))
    refs_end = next(i for i, l in enumerate(lines) if i > end and l.startswith("（番号は"))
    cite_map, blocks, pending_sub = {}, [], None
    i = start
    while i < end:
        line = lines[i].rstrip()
        i += 1
        if not line:
            continue
        if line.startswith("## "):
            num, title = line[3:].split(" ", 1)
            blocks.append({"kind": "heading", "text": num.rstrip(".").translate(ZEN) + "．" + clean(title)})
        elif line.startswith("### "):
            num, title = line[4:].split(" ", 1)
            pending_sub = "＜" + num.replace(".", "・") + "＞" + clean(title) + "　　"
        elif line.startswith("**表1**"):
            caption = clean(line)
            rows = []
            while i < end and not lines[i].startswith("|"):
                i += 1
            while i < end and lines[i].startswith("|"):
                raw = [c.strip() for c in lines[i].strip("|").split("|")]
                cells = [[clean(c), c.startswith("**")] for c in raw]
                if not set("".join(raw)) <= set("-: "):
                    rows.append(cells)
                i += 1
            note = ""
            while i < end and not lines[i].strip():
                i += 1
            if i < end and lines[i].startswith("＊"):
                note = clean(lines[i]); i += 1
            blocks.append({"kind": "table", "caption": caption, "rows": rows, "note": note})
        elif line.startswith("**図"):
            blocks.append({"kind": "figure", "caption": clean(line)})
        else:
            text = clean(line)
            r = runs(text, cite_map)
            if pending_sub:
                r.insert(0, [pending_sub, "sub"]); pending_sub = None
            blocks.append({"kind": "para", "runs": r})
    refs = {}
    for line in lines[end + 1:refs_end]:
        m = re.match(r"〔(\d+)〕(.*)", line.strip())
        if m:
            refs[int(m.group(1))] = m.group(2).strip()
    blocks.append({"kind": "refhead", "text": "文　　献"})
    for old, new in sorted(cite_map.items(), key=lambda kv: kv[1]):
        blocks.append({"kind": "ref", "text": f"({new})　{refs[old]}"})
    unused = sorted(set(refs) - set(cite_map))
    Path(out_path).write_text(json.dumps({"blocks": blocks, "cite_map": cite_map, "unused_refs": unused},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
    print("blocks", len(blocks), "cite_map", cite_map, "unused", unused)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
