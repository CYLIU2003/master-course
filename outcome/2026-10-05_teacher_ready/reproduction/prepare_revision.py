"""Read frozen evidence and preserve the commented source deck for a new revision."""
import csv
import hashlib
import json
import posixpath
import re
import sys
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as E

ROOT = Path(__file__).resolve().parents[3]
BUILD = Path(sys.argv[1]).resolve()
SOURCE = ROOT / "outcome/2026-10-02_teacher_comments/september_progress_20261002_v5_teacher_revised.pptx"
EVIDENCE = ROOT / "outcome/2026-09-28_september_presentation/evidence"
SOURCE_SHA = "c08580588af9ea513907200dd80676ddb2ae42e2793c74d0e49255ceeeadeb64"
MANIFEST_SHA = "52f6b6288ecf9295bad622a4f71de16b2e1cac0094934326e382cecd4de6dd87"
N = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
     "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
     "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def serialize(root):
    return E.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def set_text(body, value, size=None):
    import copy
    first = body.find(".//a:rPr", N)
    rpr = copy.deepcopy(first) if first is not None else E.Element("{" + N["a"] + "}rPr")
    if size is not None:
        rpr.set("sz", str(size))
    old = body.find("a:p/a:pPr", N)
    ppr = copy.deepcopy(old) if old is not None else None
    for para in list(body.findall("a:p", N)):
        body.remove(para)
    for line in value.split("\n"):
        para = E.SubElement(body, "{" + N["a"] + "}p")
        if ppr is not None:
            para.append(copy.deepcopy(ppr))
        run = E.SubElement(para, "{" + N["a"] + "}r")
        run.append(copy.deepcopy(rpr))
        E.SubElement(run, "{" + N["a"] + "}t").text = line


def shape(root, ident, value, size=None):
    matches = [sp for sp in root.findall(".//p:sp", N)
               if sp.find(".//p:cNvPr", N).get("id") == str(ident)]
    assert len(matches) == 1, ident
    set_text(matches[0].find("p:txBody", N), value, size)


def append_notes(parts, slide, value):
    rel = f"ppt/slides/_rels/slide{slide}.xml.rels"
    target = next(r.get("Target") for r in E.fromstring(parts[rel])
                  if r.get("Type").endswith("/notesSlide"))
    name = posixpath.normpath(posixpath.join("ppt/slides", target))
    root = E.fromstring(parts[name])
    bodies = [sp.find("p:txBody", N) for sp in root.findall(".//p:sp", N)
              if sp.find("p:nvSpPr/p:nvPr/p:ph", N) is not None
              and sp.find("p:nvSpPr/p:nvPr/p:ph", N).get("type") == "body"]
    assert len(bodies) == 1
    previous = "\n".join("".join(t.text or "" for t in p.findall(".//a:t", N))
                          for p in bodies[0].findall("a:p", N))
    set_text(bodies[0], previous + "\n\n2026-10-05の説明：\n" + value)
    parts[name] = serialize(root)


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA, "Source deck changed; preserve newer user edits"
    assert hashlib.sha256((EVIDENCE / "manifest.json").read_bytes()).hexdigest() == MANIFEST_SHA
    manifest = json.loads((EVIDENCE / "manifest.json").read_text("utf-8"))
    for relative, expected in manifest.items():
        assert hashlib.sha256((EVIDENCE / relative).read_bytes()).hexdigest() == expected, relative
    weeks = read_csv(EVIDENCE / "weekly_summary.csv")
    assert len(weeks) == 12
    for row in weeks:
        assert abs(sum(float(row[key]) for key in ["vehicle_usage_cost_jpy", "electricity_cost", "fuel_cost", "co2_cost", "contract_overage_cost"]) - float(row["total_cost"])) < 1e-6
    pair = {r["week"]: r for r in weeks}
    assert float(pair["2025-04-07"]["vehicle_usage_cost_jpy"]) == float(pair["2025-05-12"]["vehicle_usage_cost_jpy"]) == 4120000
    may = [r for r in read_csv(EVIDENCE / "2025-05-12/energy_15min.csv")
           if r["interval_start_jst"][:10] in ["2025-05-12", "2025-05-13"]]
    assert len(may) == 192
    main_slides = [1, 2, 3, 4, 5, 6, 12, 13, 14, 19, 40, 41, 15, 17, 18, 7, 44, 42]
    order = main_slides + [i for i in range(1, 45) if i not in main_slides]
    mapping = {old: new for new, old in enumerate(order, 1)}
    record = {"source": str(SOURCE), "source_sha256": SOURCE_SHA, "evidence_manifest_sha256": MANIFEST_SHA,
              "evidence_files_verified": len(manifest), "weeks": weeks, "may_energy": may,
              "main_slides": len(main_slides), "slide_order": order, "old_to_new": mapping,
              "weather_curves": read_csv(EVIDENCE / "weather/seasonal_curves.csv"),
              "weather_labels": read_csv(EVIDENCE / "weather/weather_labels.csv")}
    curtailed = [r for r in may if r["interval_start_jst"].startswith("2025-05-13") and float(r["pv_curtailed_kwh"]) > 1e-6]
    assert len(curtailed) == 23
    assert all(abs(float(r["bess_soc_end_kwh"]) - 4800) < 1e-6 for r in curtailed)
    record["may13_curtailment_evidence"] = {"intervals": 23, "all_end_bess_kwh": 4800,
                                          "first": curtailed[0]["interval_start_jst"], "last": curtailed[-1]["interval_start_jst"]}
    (BUILD / "data.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    with ZipFile(SOURCE) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    for number in range(1, 40):
        name = f"ppt/slides/slide{number}.xml"
        root = E.fromstring(parts[name])
        if number == 1:
            shape(root, 9, "修士論文研究　進捗説明資料")
            shape(root, 6, "太陽光発電を活用した電気バスの\n連続7日間運行・充電計画", 3200)
            shape(root, 7, "各月代表週における運用成立性と電力利用の評価\n2025年各月の12代表週", 2100)
            shape(root, 3, "日をまたぐ充電と電力利用を、計画・時系列・費目で評価する", 1800)
            shape(root, 4, "計算条件に限った週次評価。統合最適性・正式研究採用は未確認。", 1400)
            shape(root, 8, "電力システム研究室　劉 承洋　／　2026年10月5日更新")
            append_notes(parts, number, "題目は10/8三者MTGで確認する案。outcome/2026-10-05_literature_novelty/TITLE_PROPOSALS.mdの学内中間発表候補に合わせた。統合最適性や研究採用を承認済みとはしない。")
        if number == 2:
            shape(root, 7, "研究の問いと、今回の評価")
            shape(root, 2, "運行要求を満たす充電計画が、7日間の電力利用と費用にどう現れるか")
            shape(root, 3, "混成車両・翌朝SOC・余剰PV充電の条件で、日をまたぐ電力利用を評価する", 1800)
            shape(root, 4, "月1週の記述的比較。手法の優越性・PVだけの因果効果は含めない。\n[1] Hendriks・Sturmberg (2024)　[2] Liuら (2024)　書誌・確認範囲はノート。", 1100)
            rows = root.findall(".//a:tbl/a:tr", N)
            values = [["評価すること", "今回示す内容"],
                      ["7日間の運用成立", "全便・帰庫・充電器・SOCを確認し、翌朝まで残量を引き継ぐ"],
                      ["電力利用と費用", "PV・系統・BESSの時系列と、買電・燃料・車両使用等を対応づける"],
                      ["月別代表週の差", "各月1週、計12週。日射と充電要求の時間的な関係を見る"],
                      ["研究の位置付け", "週次充電やPV/BESSは既往研究あり[1,2]。対象路線の事例評価"]]
            assert len(rows) == len(values), len(rows)
            for row, vals in zip(rows, values):
                cells = row.findall("a:tc", N)
                assert len(cells) == len(vals)
                for cell, text in zip(cells, vals):
                    set_text(cell.find("a:txBody", N), text, 1700)
            append_notes(parts, number, "目的は最適化手法の優劣ではなく、所与の運行・設備条件で得た計画の成立と電力利用・運用評価額を示すこと。月別差には予測・配車・探索・在庫の差も含む。未実施の投資採算や補助金算定を結果にしない。")
            append_notes(parts, number, "[1] Hendriks & Sturmberg (2024), An integrated model of electric bus energy consumption and optimised depot charging, npj Sustainable Mobility and Transport, doi:10.1038/s44333-024-00008-2。週次充電・定置電池・受電ピークを扱うが、PVは対象外。出版社本文を再確認。[2] Liu et al. (2024), Electric bus charging scheduling problem considering charging infrastructure integrated with solar photovoltaic and energy storage systems, Transportation Research E 187,103572, doi:10.1016/j.tre.2024.103572。著者所属大学の要旨 https://research.chalmers.se/en/publication/542226 を確認。PV/蓄電設備を含む充電計画が既にあることだけを参照。全数式比較・網羅的な新規性調査ではない。7日間だけを新規性としない。")
        if number == 4:
            shape(root, 4, "PVは水平面GHI比例の推計（設置角・方位未反映）。受電200 kWは料金のモデル閾値で設備上限ではない。", 1550)
        if number == 5:
            shape(root, 2, "2024年1年の平均的日射で計画し、2025年の履歴推定で毎時更新・評価する", 1700)
            for cell in root.findall('.//a:tc', N):
                body=cell.find('a:txBody', N)
                value='\n'.join(''.join(t.text or '' for t in p.findall('.//a:t',N)) for p in body.findall('a:p',N))
                if '最終翌朝' in value: set_text(body,value.replace('最終翌朝','7日目の翌朝'),1700)
            shape(root, 3, "営業168時間に、7日目の翌朝の充電・受電・費用を加える", 1800)
            append_notes(parts, number, "予測は2024年のclimatology。2025年天候別標準カーブは記述統計で、今回の予測に使用していない。未来の2025年日射を既知として前日の計画に使ったものではない。")
        if number == 18:
            shape(root, 2, "同じ1,704便・206台日。表示は万円、原値は保存済みの運用費台帳", 1700)
            shape(root, 4, "超過費は200 kW超の電力量×500円/kWhという仮定。差には配車・予測・計算の打切り・在庫差も含む。", 1500)
            cells = root.findall(".//a:tbl/a:tr", N)[3].findall("a:tc", N)
            set_text(cells[0].find("a:txBody", N), "燃料消費評価", 1700)
        if number == 14:
            shape(root, 4, "設備・保守・劣化・人件費は未計上。超過費は仮定料金、燃料は距離による消費評価（給油支払額ではない）。", 1400)
        if number == 12:
            shape(root, 2, "日付別ダイヤ・PVと、日をまたぐ残量継承。保存済み計画とCSVを照合", 1700)
        if number == 19:
            shape(root, 4, "BESSは余剰PVで充電。週末の在庫を初期値へ戻す制約は課していない。", 1500)
        if number == 20:
            shape(root, 7, "補足：3月・11月と天候分類の回答概要")
        # Renumber only verified footer objects and explicit supplement references.
        for node in root.findall(".//a:t", N):
            if node.text:
                node.text = re.sub(r"補足([0-9]+)", lambda m: "補足" + str(mapping[int(m.group(1))]), node.text)
        shape(root, 5, str(mapping[number]))
        parts[name] = serialize(root)
    with ZipFile(BUILD / "patched_source.pptx", "w", ZIP_DEFLATED) as z:
        for name, raw in parts.items():
            z.writestr(name, raw)
    protected = [n for n in parts if n.startswith(("ppt/charts/", "ppt/comments/", "ppt/embeddings/"))]
    with ZipFile(SOURCE) as a, ZipFile(BUILD / "patched_source.pptx") as b:
        assert all(a.read(n) == b.read(n) for n in protected)
    print(json.dumps({"source_verified": True, "evidence_files": len(manifest), "source_charts_comments_workbooks_preserved": True,
                      "main": len(main_slides), "total": len(order)}))


if __name__ == "__main__":
    main()
