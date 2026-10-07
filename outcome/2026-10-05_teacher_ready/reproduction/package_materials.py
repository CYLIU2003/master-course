"""Package the explanation, notes and verification for the delivered revision."""
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[3]
DEST = Path(__file__).resolve().parents[1]
BUILD = Path(sys.argv[1]).resolve()
EVIDENCE = ROOT / "outcome/2026-09-28_september_presentation/evidence"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (DEST / name).write_text(value.strip() + "\n", encoding="utf-8")


def main():
    slides = json.loads((BUILD / "slides.json").read_text("utf-8"))
    inventory = json.loads((BUILD / "revision_inventory.json").read_text("utf-8"))
    source = json.loads((BUILD / "data.json").read_text("utf-8"))
    pptx = DEST / "research_progress_20261005_teacher_ready.pptx"
    pdf = DEST / "research_progress_20261005_teacher_ready.pdf"
    assert digest(pptx) == inventory["sha256"]
    assert len(PdfReader(pdf).pages) == 18
    assert digest(Path(source["source"])) == source["source_sha256"]
    assert len(slides) == 44 and len([s for s in slides if not s["hidden"]]) == 18

    write("README.md", r"""
# 先生コメントを踏まえた研究進捗資料（2026-10-05）

発表の順序を、**研究の問い → 計算条件 → 連続7日間の成立 → 月別の電力・費用 → 具体的な時系列 → 結論と次の確認**に組み直しました。新しい最適化計算は行わず、固定f524eca2の保存12週と2025年Solcast履歴の値を使っています。

## 使うファイル

- **research_progress_20261005_teacher_ready.pptx**：編集可能な本文18枚＋非表示の補足26枚。図表50個はPowerPointのネイティブチャート。先生のコメント11件と元の46個のExcelデータを保持。
- **research_progress_20261005_teacher_ready.pdf**：本文18枚。通常の発表・確認用。補足はPPTXで見ます。
- [speaker_notes.md](speaker_notes.md)：本文の話し方、質問への短い答え、補足ページの案内。
- [teacher_response.md](teacher_response.md)：埋め込み11コメントの原文、何をどう直したか、参照ページ、残る検証。
- [RESEARCH_EXPLANATION.md](RESEARCH_EXPLANATION.md)：研究の意味と、言えること・まだ言えないこと。
- [claude_review.md](claude_review.md)：実際のClaude Opus 5.5/highとの2回のレビューと採否。原文はreview/へ保存。
- data/：週次費用、4月・5月比較、5/12〜13時系列、天候カーブ・分類のCSV。
- [verification.json](verification.json)、[source_manifest.json](source_manifest.json)、[bundle_manifest.json](bundle_manifest.json)：確認範囲と原本・成果物のSHA256。
- [REBUILD.ps1](REBUILD.ps1)、reproduction/：AI・API・ソルバーを使わない再生成入口。

## 今回の大きな変更

1. 本文を18枚に絞り、内部管理用の名前・hash・詳細月別図をノートと補足へ移しました。シナリオ名「仮・正式用」はユーザー指定として維持。
2. 4月と5月のPV総量差約1%に対し、費用差57.6万円を費目へ分解。仮定単価500円/kWhのもとで約91%が超過モデル費の差です。
3. 5/12〜13のPV・充電・買電・BESSを同じ時刻で表示。翌未明の買電と同日の日中の抑制を分けて説明し、代替計画で回避できないとまでは主張しません。
4. BESSの初期在庫と終端残量を、費用・季節比較より先に示しました。取り崩しを当該週のPV効果や永続的な節約としません。
5. 雨分類・GHI比・P10/P90・除外日の意味を説明。夏の雨20日中、明るい昼と15時以降の降水の両条件を満たすのは2日で、「夕立が多い」とは説明しません。

横軸の日付は各日の中央、日境界は薄い破線です。数値が表せるページでは見出しに伝える内容を置き、定義ページは主題を示します。

## 発表時に維持する条件

12週は2025年の各月1週という**独立した代表週**で、年間連続運用や月平均ではありません。2026年ダイヤ×2025年気象の仮想運用評価で、予測は2024年1年のclimatologyです。天候標準カーブは2025年履歴の記述統計で、今回の予測学習には使っていません。

「成立」は入力した車両・設備条件に対する保存結果の確認です。正式研究採用のBLOCKED/DIAGNOSTIC、図表復旧元のFAILEDは保持。週間統合最適性、実設備の運用保証、PV単独の因果効果、設備投資や補助金額の算定は未確認です。燃料費は距離由来の消費評価で、給油の支払額ではありません。

**残る技術確認は2点**：同じ配車・SOC等の条件で充電時間を変えた比較、設置角・方位を確認した設置面日射の別入力版評価。これらは資料編集だけで解決した扱いにしません。

表紙は[最新の題目候補](../2026-10-05_literature_novelty/TITLE_PROPOSALS.md)に合わせた案です。10/8三者MTGでの承認は未取得。[近接13編と貢献の検討](../2026-10-05_literature_novelty/README.md)も併読してください。

## AIなしで再生成する

この資料フォルダだけを移しても原本は揃いません。C:/master-course内の元PPTX、evidence、tools/thesis_authoring/export_presentation.ps1と、配置済みのPython/Node/Artifact Tool・Presentations検査ツール、Microsoft PowerPointが必要です。既存の環境で動作確認済みです。

PowerShellから：

```powershell
cd C:\master-course
powershell.exe -NoProfile -ExecutionPolicy Bypass -File outcome/2026-10-05_teacher_ready/REBUILD.ps1
```

新しいoutput/presentation_rebuild_日時/へPPTX・PDF・検証結果・全44枚の画像を生成します。原本SHA、固定CSV102ファイル、表と費用の一致を確認し、違えば停止。既存PPTX/PDF/作業先は上書きしません。再生成したスライド画像は、人が全ページを見てから使います。見た目の検査は自動の構造検査と別です。

原本：../2026-10-02_teacher_comments/september_progress_20261002_v5_teacher_revised.pptx。データ：../2026-09-28_september_presentation/evidence/。先生編集原本と旧資料は保持。今回の途中版はoutput/presentation_finish_20261005/intermediate/へ移して、ここには提出候補1版を置いています。

この配布資料のhash・文書参照・11コメント回答・PDF本文の検査だけなら、`reproduction/verify_delivery.py`を配置済みPythonで実行します。AI・ソルバーは使いません。図表を変更した後は数値検査に加え、全ページを再表示して確認します。
""")

    speeches = [
        "太陽光を利用する営業所について、1日だけでなく連続7日間の運行と充電を扱います。今日は成立した計画、電力の使われ方、費用の違いを示します。題目は10/8に確認する候補です。",
        "問いたいのは、毎日の運行と翌朝のSOCを満たすとき、太陽光・買電・蓄電池がどう使われるかです。7日間なら平日と土休日、前日の残量が翌日に与える影響を一緒に見られます。各月1週を使うことで、違う日射条件の計画を並べます。週次やPV自体を分野初とする研究ではありません。",
        "渋21・22・23を対象に、電気バスと燃料車を混ぜた車両群を使います。太陽光は営業所で発電し、まずバス充電に使い、その余剰を定置電池へ入れる条件です。BEVの車載電池とBESSは別に扱います。",
        "車両・充電器・PV・蓄電池の数値は、この実験で固定した条件です。車載SOCは20〜90%、翌朝出庫前までに90%を満たします。200kWは有料超過を評価するモデル閾値で、受電設備の絶対上限ではありません。ここを実設備の保証と読み替えません。",
        "前日の計画は2024年1年の平均的日射に基づき、毎時の更新と評価は2025年の履歴推定を使います。天候標準カーブは記述統計で、予測には使っていません。営業7日間の168時間に、最後の帰庫から翌朝までの充電と費用を含めています。",
        "各月から事前に選んだ月曜始まりの1週間、合計12週です。これは四季4ケースや12か月連続運用ではありません。各週は平日・土休日を含み、結果を見て安い週を選んだものではありません。代表性の偏りは補足27で確認できます。",
        "保存された12週の計画について、各週1,704便、日をまたぐ残量と電力収支、翌朝を含む費用を原値に照合しました。新しい独立した全モデル監査や最適性証明という意味ではありません。図表の復旧と求解成功も分けています。",
        "PV推定量と、バスへ直接渡した分、蓄電池へ入れた分、抑制、買電を月別に示します。PVからBESSへ入れて後で放電する電力を、PV利用として二重に加えません。また、週初めにBESSへ入っていたエネルギーは、その週のPVとは別です。",
        "総費用は車両日費の比率が大きいため、電力関連などの内訳を別に見ます。超過費は200kWを超えた電力量に500円/kWhを掛けた仮定です。設備・保守・劣化・人件費は未計上なので、実営業所の全支出や設備投資採算とは呼びません。",
        "BESSは各週3,000kWhから始めますが、終端を初期へ戻す制約はありません。週末残量には差があり、初期在庫を使う分も費用と電力利用に影響します。この結果を52回繰り返せる節約としては扱いません。",
        "4月と5月はPV総量が約1%しか違いませんが、モデル費用は5月が57.6万円高いです。車両日費はともに412万円で変わらず、差の約91%は超過モデル費です。配車・予測・計算の打切り・終端在庫も違うため、PVが費用を悪化させたという因果結論にはしません。",
        "週積算では見えない部分を5月12日と13日で見ます。12日はPVが少なくBESSが下限へ達し、13日未明に買電が集中しています。その後13日の日中にはPVを抑制する区間があり、23区間すべてでBESS終端残量は上限4,800kWhです。夜と昼は同時ではありません。この配分が最良か、充電をずらせるかは別の比較が必要です。",
        "3月と11月は同じ7日間の目盛りで比較します。どちらも夜間の買電が見えますが、ピークの高さだけでは週の費用は説明できません。超過している時間と電力量も確認します。",
        "ピーク周辺を同じ時間幅で拡大すると、3月と11月ともPV供給がゼロ、BESSは下限、複数台が翌朝目標へ同時充電しています。この区間の充電電力を系統が供給した理由は確認できます。ただし、04:15に集中することが不可避だったとはまだ言えません。",
        "3月と11月の総費用差は101.64万円で、超過モデル費の差が90.96万円です。ピーク値だけでなく、超過電力量と費目の対応が説明に必要です。各段階のgapは週間統合のgapではなく、月の費用順位が最適費用順位と証明されたわけでもありません。",
        "天候分類はSolcast履歴推定の降水強度と日射を使います。まず昼間の降水1mm以上を雨とし、それ以外の日でGHIと晴天時GHIの積算比を使います。3月3日は雨か雪かの降水形態を確認できないため分類からだけ除外し、週次計算からは消していません。",
        "雨という日単位の分類でも、一部の時間に明るい日があります。夏の雨20日のうち、10〜14時が明るい日は6日、そのうち15時以降の昼間降水も1mm以上なのは2日です。夕立が多いとは言えません。平均とP10/P90は時刻ごとの集計で、実在する1日の曲線や予測区間ではありません。",
        "今回の成果は、日をまたぐ運行・充電の12代表週を確認し、電力利用と費用差を時系列と費目で説明したことです。次は同じ配車で夜間充電を分散できるか、設置面日射に変えると評価がどう変わるかを確認します。費用低減と導入経済性は、この電力・運行評価を土台に検討する目的として残しますが、投資採算や補助金額はまだ算定していません。",
    ]
    out = ["# 発表者ノート（本文18枚）", "2026-10-05。本文は次の順で話します。補足は質問に応じて示し、全部を順番に読み上げません。目安は12〜15分ですが、指定時間に合わせて練習してください。"]
    for slide, speech in zip(slides[:18], speeches):
        out.extend([f"## {slide['number']}. {slide['title']}", speech])
    out += ["## 質問に対する短い答え", "- **なぜ7日か**：平日・土休日の違いと、翌日へ引き継ぐ車両/BESS残量を同じ運用として評価するためです。",
            "- **PVが増えたのに費用が高い理由は**：週総量だけでは充電との時刻整合が分かりません。保存計画では夜間買電と日中抑制があり、費用差の大部分は仮定の超過費です。PV単独の効果や最良の時間配分は未証明です。",
            "- **本当に最適か**：制約を満たす保存計画を条件付きで評価しています。二段階・rollingの各gapを週間統合最適性とは呼びません。",
            "- **来週も同じ節約ができるか**：初期在庫を取り崩す独立週なので、そのまま繰り返す節約とは言えません。初期・終端を併記しています。",
            "- **実営業所で受電できるか**：設備根拠が未確定の仮定条件です。料金閾値200kWと物理上限は別です。",
            "- **研究として何が残るか**：対象路線の運行要求、翌朝SOC、有限充電器と日別PVを対応づけ、必要な買電・PV利用・費用と改善余地を定量化する事例評価です。7日/PV/季節比較自体を初としません。",
            "## 補足ページ", "19〜22：季節別の平均/P10/P90。23：3月/11月の電力指標。25〜26：月別費用表。27：週の代表性。28：前提。29〜40：月別の電力/SOC。41：雨分類の実日。42：GHI/設置面。43：夜間ピーク。44：同じ6時間だけで配分する算術確認（週間最適性の下界ではない）。",
            "PPTX内の詳細ノートはembedded_notes.mdへ原文抽出。旧ノートには履歴や元ページ番号もあるため、発表原稿は本ファイルを優先します。"]
    write("speaker_notes.md", "\n\n".join(out))
    write("embedded_notes.md", "# PPTXに埋め込まれた詳細ノート\n\n元ノートを保持した履歴付きの記録です。原本SHA・判定・内部管理情報を含みます。発表の話し方はspeaker_notes.md。\n\n" + "\n\n".join(f"## {s['number']}. {s['title']} {'（非表示補足）' if s['hidden'] else ''}\n\n{s['notes']}" for s in slides))

    comments = json.loads((ROOT / "outcome/2026-10-02_teacher_comments/reproduction/comments.json").read_text("utf-8"))
    responses = [
        ("16", "説明を訂正", "降水はSolcast historic radiation_and_weatherのprecipitation_rate [mm/h]の履歴推定です。雨量計実測ではありません。15分強度×0.25hを昼間区間で合算する式と出典を示しました。", "weather/weather_labels.csv、元ノートのSolcast出典"),
        ("16", "定義を訂正", "雨優先なので『雨に当たらない日』が必要です。比Rの分子は昼間積算GHI、分母は同じ区間の積算clearsky_ghi。昼間はclearsky_ghi≥20W/m²で定義し、非雨の日にR≥0.7なら晴れ、それ以外はくもりと明記しました。", "天候分類規則とweather_labels.csv"),
        ("16", "除外理由を訂正", "雪と確認したわけではありません。3/3の低温降水は雨/雪の形態を判別できず、分類からのみ除外。3月週の運行/PVには含めました。", "2025-03-03の分類記録、週次原値"),
        ("16", "対象を具体化", "不明なのは雨/雪等の降水形態です。気温と降水強度だけで雪と断定しない説明にしました。", "取得項目と分類記録"),
        ("16〜17、19〜22", "統計の意味を訂正", "平均、P10、P90は季節×分類ごとの各時刻の経験分布です。実在する1日、予測区間、平均の信頼区間とは区別し、日数を表示しました。", "weather/seasonal_curves.csv"),
        ("17、20、41", "日別データで回答", "夏の雨20日中、10〜14時の積算GHI比≥0.7は6日。その中で15時以降の昼間降水≥1mmも満たすのは2日。雨分類でも明るい時間があると説明できますが、『夕立が多い』とは支持できません。7/10の例と探索集計であることを残しました。", "weather_labels.csv、元の追加天候集計"),
        ("4、17〜18、42", "限界を訂正／計算は未実施", "現行は水平面GHIとGHI比例PVです。設置角・方位を反映した設置面日射は必要な次の確認として明示。設置面へ直した結果とは改称しません。", "既存PV換算条件。角度/方位確認と別入力版再評価が残る"),
        ("7", "表を聴衆向けに改稿", "管理用判定を読む表から、全対象便、車両/充電制約、電力収支、翌朝と費用、解の位置付けを説明する表へ変更。根拠は保存済み計画とCSVの照合で、新しい全原本独立監査とはしません。", "原物理判定・weekly_summary.csv・manifest"),
        ("11〜15、43〜44", "供給理由を追加／回避可能性は未検証", "ピーク区間はPV0、BESS下限、8/10台が同時充電し系統が供給。さらに4月/5月の費目差と5/12〜13時系列を追加し、集計だけでなく残量・時刻へつなぎました。ただし別の充電時間・配車なら回避できるかは未計算。『最適/不可避』は主張しません。", "各月energy_15min/charging/SOC、4月5月差、night_energy_relaxation.csv"),
        ("本文18枚、24の補足、ノート", "取捨選択", "BLOCKED等の管理記号はノート・回答書に残し、本文は日本語で計算範囲と限界を説明。旧まとめは補足へ移動し、本文18を結論・次の確認に置き換えました。", "原11コメント・元判定を保持"),
        ("28の補足、ノート", "取捨選択", "hash、CO₂図表警告、内部状態の説明はノート/記録へ。聴衆が解釈に必要な気象/ダイヤ年、PV面、仮定費用、在庫、未証明範囲を残しました。", "source_manifest・verification・原ノート"),
    ]
    out = ["# 先生の11コメントへの回答と変更理由", "2026-10-05。先生編集原本のコメントは削除・自動解決していません。以下の番号は原コメント一覧の番号で、参照ページは今回の44枚版です。『資料の説明を直した』ことと『数理・入力・代替計算が完了した』ことを分けています。"]
    for comment, response in zip(comments, responses):
        pages, state, answer, evidence = response
        out += [f"## {comment['index']}. 元ページ{comment['slide']} → 今回ページ{pages}", "> " + comment["text"].replace("\n", "\n> "), f"**対応：{state}。** {answer}", f"**根拠/残件：** {evidence}。"]
    out += ["## 今回見つけて直した説明上の問題", "- 10/03の検討メモだけに4月/5月の車両日費を410万円とする誤記があり、412万円へ訂正。原CSVと元PPTXは正しかったため、計算数値は変更していません。",
            "- 『未明の買電と日中の抑制が重なる』は同時刻と誤読するため、『翌未明に買電し、同日の日中にはPVを抑制する』へ修正。",
            "- `balanced`は初期終端一致を意味しないので、本文は『週末の在庫を初期値へ戻す制約は課していない』と明記。",
            "- 『2024年の平均的日射』に『1年』を追加。平年値や2025年標準カーブを用いた予測と混同しない。",
            "- 新しいグラフの数値は表示用に小数6桁へ丸め、原CSVは原値を保持。Officeの微小なキャッシュ差は元Excel値へ一致させ、元46ワークブックのhashを保持。",
            "## 先生に今出せる回答の範囲", "コメント7の設置面PV再評価と、コメント9の別充電計画の比較は未実施です。今回は現結果の説明と根拠を明確にした提出候補であり、この2点の研究課題や正式研究採用を完了とするものではありません。題目の承認も10/8三者MTGで確認する案です。"]
    write("teacher_response.md", "\n\n".join(out))

    write("RESEARCH_EXPLANATION.md", """
# 研究の意味と、説明の組み立て

## 何を明らかにする研究か

所与の混成車両・充電設備・日別ダイヤで、平日と土休日を含む連続7日間の運行・充電を成立させ、その運行要求を満たすときのPV・買電・BESS利用と費用を評価する研究です。各月1週は異なる入力条件を比べる設計で、最適化手法の証明や分散システム開発そのものが主目的ではありません。

1日では前日からの残量や翌朝の充電が切れて見えるため、7日間の状態継承を追跡します。月別の積算量だけでなく、充電できる時間、翌朝目標、PVが出る時刻、BESS在庫と対応させることが説明の軸です。

週次充電、PV/BESS、季節比較には既往研究があります。本研究の価値は『7日を初めて扱った』という主張ではなく、対象路線の運行要求と電力利用を結び付けた再確認可能な事例評価、及び改善余地と制約の定量化に置きます。[近接13編と比較範囲](../2026-10-05_literature_novelty/README.md)を参照してください。今回の本文には、範囲を確認した近接2編のみを例として示しています。

## どこまで結果で言えるか

**確認した記録**：固定12週の保存計画・物理判定・費用CSV・出典hash。各週1,704便、車両状態と翌朝を含む範囲を照合。新規の全native再監査や週間統合最適性の証明ではありません。

**定量的な観察**：4月/5月のPV総量差は281.1375kWh（約1.07%）、モデル総費用差は576,380.853975円。車両日費はともに4,120,000円で、超過モデル費差524,900.184033円が総差の91.0683%です。これは仮定単価500円/kWhで固定計画を評価した差で、単価を変えて再最適化した感度分析ではありません。

**時系列で説明できること**：5/12の低PVとBESS下限、その翌未明の買電、5/13の日中PV抑制が同じ記録に存在します。抑制が正の23区間ではBESS終端が全て上限4,800kWhでした。3月/11月ピークの区間ではPVが0、BESS下限、複数車両充電を系統が供給しています。

**まだ言えないこと**：この配分が不可避・最良であること、PV単独の因果効果、実設備で保証された運用、在庫取り崩しを繰り返す年間節約、設備投資採算・最適補助金額。『供給源を説明できる』ことと『集中の回避可能性を説明できる』ことは違います。

## 次に研究を強める少数の確認

1. 1〜2週について同じ配車・運行/SOC・設備条件で可行な基準充電と現計画を比較し、夜間の分散可能性を確認する。帰庫〜翌出庫の全窓、充電口占有、初終端在庫、情報条件をそろえ、削減と呼ぶ根拠を作る。
2. 設置角・方位を確認し、水平面GHIを設置面日射へ変換した別入力版で評価する。既存12週の値を補正済みとして後から置き換えない。

今回の資料は、既にある週次成果を説明可能にする改稿です。少数対照や設置面の再計算はこの改稿では開始していません。費用低減と導入の経済性を研究目的に残し、投資・保守/交換・実料金・比較対象等が揃った段階で支援水準へ展開します。
""")

    review = DEST / "review"
    review.mkdir(exist_ok=True)
    prior = ROOT / "output/presentation_finish_20261005"
    for old, new in [("claude_outline.md", "opus_round1.md"), ("claude_final.md", "opus_round2.md")]:
        shutil.copy2(prior / old, review / new)
    checks = []
    for stem in ["claude_outline", "claude_final"]:
        response = json.loads((prior / f"{stem}.json").read_text("utf-8"))
        assert not response.get("is_error")
        assert "claude-opus-5-5" in response["modelUsage"]
        checks.append({"source": str(prior / f"{stem}.json"), "sha256": digest(prior / f"{stem}.json"),
                       "is_error": response["is_error"], "modelUsage_keys": list(response["modelUsage"])})
    write("claude_review.md", """
# Claudeとの内容レビューと採否

2026-10-05。ローカルClaude Codeを`--model opus --effort high --safe-mode --tools '' --strict-mcp-config --no-session-persistence`で2回実行。両応答のmodelUsageはclaude-opus-5-5、is_error=falseです。今回は提示したスライド文字・根拠要約の内容レビューで、画像・CSV原本の独立再検算・モデル監査・教員承認は行っていません。実図と原値はCodex側で確認しました。

## 第1回：構成・根拠・研究の主張

[原文](review/opus_round1.md)。BESS境界条件を比較より先に示す、天候の本文を2枚に絞る、4月/5月の費目と時系列を加える、超過費・燃料費・統計の意味を明確にする提案を採用しました。既往研究の位置付けも本文とノートへ追加。

一方、提供要約からの『PV容量がない』という指摘は、原スライド4に1,000kWがあるため欠陥としません。全ての題を結論文へ変える提案は、定義ページには主題が必要なため一律には採用していません。『7日』だけの新規性や、固定6時間の算術下限を週間最適性へ転用する説明はしていません。

## 第2回：本文18枚の再レビュー

[原文](review/opus_round2.md)。必須2点は反映済みです。

- 未明と日中は同時刻ではないため、『重なる』を『翌未明に買電し、同日の日中にはPVを抑制する』へ改稿。
- 内部名balancedを本文から外し、『週末の在庫を初期値へ戻す制約は課していない』と明記。

単年2024年であること、保存済み計画/CSVの照合範囲、燃料消費評価、内部管理用語の移動も反映。「仮・正式用」はユーザー指定のシナリオ名なので維持。

第2回の短い総評にある『雨20日のうち15時以降の降水は2日』は、明るい昼との両条件を省略しているため、そのまま資料へ転記しません。正しい集計は20日中で昼が明るい6日、そのうち15時以降の昼間降水1mm以上もある2日です。

設置面PVと別充電計画の比較が未実施という留保を採用。未実施点を文章で解決済みとしません。最後の表紙は同日の別文献検討で得た最新版題目へそろえた文字変更で、再度Claudeを呼ぶ代わりにネイティブ表示と範囲を確認しました。
""")
    write("review/settings.json", json.dumps({"requested_model": "opus", "effort": "high", "tools_enabled": False,
          "safe_mode": True, "calls": checks, "scope": "provided text and evidence summaries; no images or independent source audit"}, ensure_ascii=False, indent=2))

    data = DEST / "data"
    data.mkdir(exist_ok=True)
    for relative, target in [("weekly_summary.csv", "weekly_summary.csv"),
                             ("weather/seasonal_curves.csv", "weather_curves.csv"),
                             ("weather/weather_labels.csv", "weather_labels.csv")]:
        shutil.copy2(EVIDENCE / relative, data / target)
    with (data / "may12_13_energy.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(source["may_energy"][0]))
        writer.writeheader()
        writer.writerows(source["may_energy"])
    with (data / "april_may_comparison.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(source["weeks"][0]))
        writer.writeheader()
        writer.writerows([r for r in source["weeks"] if r["week"] in ["2025-04-07", "2025-05-12"]])

    write("slide_inventory.json", json.dumps([{k: s[k] for k in ["number", "title", "hidden", "native_charts", "native_tables"]} for s in slides], ensure_ascii=False, indent=2))
    shutil.copy2(BUILD / "verified_final_validation.json", DEST / "presentation_validation.json")
    same = [i for i in range(2, 45) if digest(BUILD / f"render/slide-{i}.png") == digest(ROOT / f"output/presentation_finish_20261005_final/render/slide-{i}.png")]
    assert len(same) == 43, "A changed slide needs a new full visual inspection"
    verification = {"date_jst": "2026-10-05", "presentation": inventory, "pdf_pages": 18,
                   "evidence_manifest_verified_files": source["evidence_files_verified"],
                   "native_rendered_slides": 44, "visually_inspected_slides": list(range(1, 45)),
                   "visual_method": "Native PowerPoint 1280x720 images. All 44 inspected; final cover newly inspected and other 43 image hashes identical to inspected v7.",
                   "final_title_only_change": True, "unchanged_rendered_images_from_v7": same,
                   "claude_content_review_rounds": 2, "teacher_comments_retained_unresolved": 11,
                   "rebuild_full_pipeline": "PASS", "existing_destination_rejected": True,
                   "helper_review": "Self-review plus native end-to-end execution. Claude reviews covered content, not these scripts.",
                   "new_solver_run": False, "formal_research_approval_changed": False,
                   "remaining_checks": ["fixed-assignment alternative charging comparison", "installation-plane irradiance with verified tilt/azimuth"],
                   "claim_scope": "Saved-plan and CSV evidence checks, source preservation and presentation content/layout; no new full native optimization audit or teacher approval"}
    write("verification.json", json.dumps(verification, ensure_ascii=False, indent=2))
    sources = [{"path": "../2026-10-02_teacher_comments/september_progress_20261002_v5_teacher_revised.pptx", "sha256": source["source_sha256"], "role": "revision source with preserved teacher comments"},
               {"path": "../2026-09-28_september_presentation/evidence/manifest.json", "sha256": source["evidence_manifest_sha256"], "role": "102 fixed evidence files"},
               {"path": "../2026-10-05_literature_novelty/TITLE_PROPOSALS.md", "sha256": digest(ROOT / "outcome/2026-10-05_literature_novelty/TITLE_PROPOSALS.md"), "role": "latest candidate title; teacher approval pending"},
               {"solver_commit": "f524eca2552a4386bd033a15bbe046c14dc09281", "role": "original experiment code, not current development HEAD"}]
    write("source_manifest.json", json.dumps(sources, ensure_ascii=False, indent=2))
    manifest = {p.relative_to(DEST).as_posix(): digest(p) for p in sorted(DEST.rglob("*")) if p.is_file() and p.name != "bundle_manifest.json" and "__pycache__" not in p.parts}
    write("bundle_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({"packaged_files": len(manifest), "slides": 44, "main": 18, "unchanged_other_slide_images": len(same), "original_source_preserved": True}))


if __name__ == "__main__":
    main()
