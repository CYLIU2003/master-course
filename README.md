# master-course

## 2026-08-08 Phase 4 full-scope diagnostic correction

- A non-formal 264-trip HTTP diagnostic at
  `output/2026-08-08/run_20260808_0601` now proves that the verified Phase 3
  dispatch has feasible recourse in the integrated model. The fixed-dispatch
  solve returned an incumbent in about 0.8 seconds and promoted all 776,752
  integrated variable values as a complete warm start.
- The prior recourse IIS was caused by a false coarse-slot conflict. Charging
  and refueling used `on <= 1 - sum(y)` across every trip touching a one-hour
  energy slot. Two sequential, non-overlapping trips in the same slot made the
  right-hand side negative even when no charging/refueling occurred. Phase 4
  now applies the no-replenishment implication separately to each assignment;
  physical trip-overlap and turnaround constraints remain unchanged.
- The integrated extractor now publishes the exact solver expressions used by
  the final-day BEV SOC constraints. Missing initial SOC, target constraints,
  or terminal expressions fail closed. The 264-trip diagnostic reports all 15
  used BEVs, return-to-initial acceptance, a maximum deviation of approximately
  `1e-6 kWh`, and zero independent physical violations.
- A time-limit result with a verified incumbent is classified as a physically
  valid, non-exact candidate. It is never relabeled optimal. A time limit
  without an incumbent remains invalid.
- This diagnostic used a dirty, non-formal tree and a one-second unrestricted
  Phase 4 budget. It is implementation evidence only. A fresh Prepare and
  clean frozen sunny/rain pair remain mandatory before any research result or
  weather comparison is accepted.

## 2026-08-08 Phase 4 integrated-recourse-certified warm start

- The first clean implementation run at commit
  `e071446cb346092719a3103e81026bcb02d82a21` exposed a stricter defect: both
  264-trip cases accepted the Phase 3 seed and wrote every advertised `Start`
  value, but the integrated model rejected that vector and reached 3,600
  seconds with zero incumbents. Therefore `Start` assignment is no longer
  treated as proof of an integrated feasible warm start.

- Frontend `phase4_integrated` runs now build a Phase 3 two-stage plan on the
  same in-memory canonical problem before starting the full integrated MILP.
  The plan is accepted only when it covers the exact trip set, Stage 2 is
  feasible, and the independent physical validator passes.
- The accepted plan is only a Phase 4 MIP start and upper bound. Phase 3 cost,
  gap, or composition is never returned as a Phase 4 result and never implies
  integrated optimality.
- Formal actual-cost Phase 4 does not inject the one-sided `used BEV >= K`
  frontier. Its seed uses the primary Phase 3 candidate plus symmetric
  adjacent-composition candidates; the final objective contains no hidden
  weather or BEV-direction preference. The frontend Phase 4 request uses a
  5% gap target so the first 13/19 seed cannot terminate immediately at the
  former 10% threshold.
- After the Phase 3 plan is checked, Phase 4 temporarily fixes only its
  assignment/path/vehicle-use decisions and solves charging, physical-charger
  occupancy, vehicle/BESS SOC, PV, BESS and grid recourse in the integrated
  model itself. Only a feasible result is promoted to a complete all-variable
  MIP start; original dispatch bounds are then restored before the unrestricted
  actual-cost search. An infeasible fixed-dispatch recourse exports IIS names,
  counts and a fingerprint and fails the formal hand-off gate.
- The formal solver-control record declares the 600-second seed budget, its
  480/120-second Stage 1/2 split, a 300-second integrated fixed-dispatch
  recourse preflight, the 3,600-second unrestricted integrated budget, and the
  4,500-second total maximum. These controls are included in the sunny/rain
  comparison hash; each case gate separately requires a feasible preflight.
- Formal evidence still requires a fresh Prepare and a clean frozen commit.
  A feasible incumbent is distinct from meeting the requested MIP gap; any
  time-limit result must publish its achieved gap without claiming global
  optimality. The recourse correction has focused-test evidence only until the
  next clean 264-trip HTTP pair completes.

## 2026-08-07 PV/BESS and optimization-control contract

- Solcast records are resampled by source/target interval overlap. Converting
  a 60-minute irradiance interval to 5/15/30-minute slots now preserves daily
  kWh instead of assigning the whole interval to only one shorter slot.
- `POST /api/scenarios/{scenario_id}/depot-assets/update` is a patch API.
  Omitted PV/BESS fields retain their saved values; explicit `pv_enabled=false`
  and `pv_generation_kwh_by_slot=[]` are honored. Changing rated PV output
  also updates the reverse area estimates and rescales a derived curve.
- PV dates, slot lengths, performance ratio, PV generation, BESS ratings, SOC
  bounds, and charge/discharge efficiencies are validated before Prepare or
  optimization. Invalid physical inputs are not replaced by hidden defaults.
- Demand charge is billed per depot meter. The objective and canonical
  accounting both use the sum of the on/off-peak demand maxima for each depot.
- The Tk solver settings expose `phase3_two_stage`, `phase4_integrated`, Stage
  1 composition/frontier controls, and the Phase 4 canonical actual-cost and
  EV-utilization controls. Quick Setup persists and reloads the same fields.

These corrections invalidate prepared inputs and optimization outputs created
before this change. Restart Tk/BFF and run a fresh Prepare. A passing code test
suite does not make a research result READY; formal runs still require a clean
frozen commit and every per-run/pair acceptance gate.

> 東急バスの BEV／ICE 混成車両を対象に、便割当、充電、PV、BESS、系統電力を一貫して評価する研究用最適化システムです。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
![UI Tkinter](https://img.shields.io/badge/UI-Tkinter-3776AB?logo=python&logoColor=white)
![Solver Gurobi](https://img.shields.io/badge/Solver-Gurobi-EE3524)

> [!IMPORTANT]
> **現在の研究公開ステータスは `BLOCKED` です。** 個別ジョブの完了、可行解、Rolling の受理、正式な研究受理は別の判定です。最新の判定理由と必要な証跡は、[研究リリースのブロッカー一覧](docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md)を確認してください。

## まず、目的に合う入口を選ぶ

| やりたいこと | 最初に読む・実行するもの |
| --- | --- |
| 画面から通常の最適化を動かす | [最短で起動する](#最短で起動する) → [最初の最適化](#最初の最適化) |
| 研究用の正式実行をする | [正式研究実行の手順](docs/notes/FORMAL_RUNBOOK_CURRENT.md) と [ブロッカー一覧](docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md) |
| モデルを教員・共同研究者に説明する | [教員レビューガイド](README_core_professor.md) |
| 日常運用、比較、障害対応を確認する | [運用ガイド](readme_operation.md) |
| 実装・検証・変更履歴を確認する | [開発ノート](DEVELOPMENT_NOTES.md) |

## このシステムでできること

- 時刻表と営業所・路線スコープから、車両ごとの便割当と回送を作成する。
- BEV の SOC、充電器、PV、BESS、系統電力、料金を制約として充電計画を評価する。
- 日初の計画に加え、1 時間ごとの Rolling 再最適化、物理スケジュール検証、実行日会計を成果物として残す。

現行ソルバには、二段階の **Phase 3** と、配車・充電・PV・BESS・系統購入を結合する **Phase 4** があります。Phase 3は大域的総費用最適解ではなく、Phase 4も現時点ではclean formal pairが未受理です。どちらも、成果物ごとの物理・会計・最適性・研究受理ゲートを越えて主張範囲を広げないでください。

## 現在の構成と扱い

| 項目 | 現在の扱い |
| --- | --- |
| 操作画面 | Tkinter + FastAPI BFF。`python run_app.py` が両方を起動します。 |
| API | FastAPI の `/api` 配下。起動後の対話的な仕様は `http://127.0.0.1:8000/docs` で確認できます。 |
| React / Tauri | まだ設計・受入基準の段階です。通常運用の手順としては扱いません。詳細は [frontend 移行仕様](docs/frontend/README.md)。 |
| 出力 | 現在の既定ルートは `output/`。各 run は通常 `output/<日付>/run_*` に保存されます。 |

```mermaid
flowchart LR
    UI[Tkinter 操作画面] --> BFF[FastAPI BFF /api]
    BFF --> CORE[配車・最適化コア]
    CORE --> ART[run 成果物]
    ART --> CHECK[Rolling・物理検証・会計・研究受理]
```

## 最短で起動する

### 前提

- Windows / PowerShell
- Python 3.11 以上（CI の検証対象は Python 3.11）
- MILP を実行する場合は、別途 Gurobi と有効なライセンス
- 利用対象の built dataset（画面のデータ状態で確認）

初回だけ、仮想環境と依存関係を準備します。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

MILP を使う環境では、Gurobi を導入・ライセンス設定したうえで `gurobipy` も追加します。

```powershell
python -m pip install gurobipy
python -c "import gurobipy as gp; m=gp.Model(); x=m.addVar(lb=0.0, name='x'); m.setObjective(x); m.optimize(); print('gurobi_ok', gp.gurobi.version())"
```

起動は次の一行です。FastAPI が起動可能になるのを待ってから Tkinter 画面を開き、画面を閉じると BFF も終了します。

```powershell
python run_app.py
```

API だけを起動して確認したい場合は、次を使います。

```powershell
python -m uvicorn bff.main:app --host 127.0.0.1 --port 8000
```

> [!NOTE]
> この checkout には配布済みの `.exe` は含まれていません。配布物を受け取っている場合は、その配布元の手順を優先してください。

## 最初の最適化

通常は、画面の案内どおり次の 4 ステップで十分です。

1. シナリオを選び、対象の運行日・営業所・路線を確認する。
2. `Quick Setup 保存` で選択内容を確定する。
3. 条件を変える必要がある場合だけ `ソルバー設定` を開く。
4. `高速実行` を押す。未 Prepare または stale のときは、画面が Prepare を先に実行してから最適化ジョブを開始します。

対象スコープ、便数、車両、充電器を実行前に明示確認したいときは、`Solver対応 Prepare` を個別に使います。Quick Setup やソルバー条件を変更した後は、必ず再 Prepare してください。

Quick Setup の数値入力では、`0` は「未入力」ではなく明示値です。たとえば、基本料金
`0 JPY/kW`、売電単価 `0 JPY/kWh`、乱数 seed `0` は、保存後の再読込と次回
Prepare でもそのまま保持されます。既定値が使われるのは項目が未設定 (`null`) の場合だけです。
入力範囲として無効な値は、別の既定値へ黙って置換せず、各入力・実行時の検証でエラーにします。

PV設備は、画面で保存した `pv_capacity_kw`（PV定格出力）を最適化入力の正本とします。
面積からの推定容量や、定格出力から逆算する必要設置面積・面積相当値は監査用の派生値であり、
保存済みの定格出力や実測営業所面積を黙って上書きしません。定格出力を変えた場合もfresh Prepareが必要です。

### 結果を正しく読む

| 表示・成果物 | 分かること | それだけでは分からないこと |
| --- | --- | --- |
| ジョブが `completed` | 非同期ジョブが終端状態になった | 可行性、物理妥当性、研究受理 |
| `solver_status=OPTIMAL` または `FEASIBLE` | 数理最適化が解を返した | Rolling、独立物理検証、正式な研究主張 |
| `rolling_execution.status=executed_and_accepted` | 保存された Rolling 連鎖が受理された | 比較対照の妥当性、研究公開の可否 |
| `teacher_release_status=READY` | 正式な研究リリースの全ゲートが通った | それ以上の一般化や統合大域最適性 |

画面の `Optimization結果` から run ディレクトリを確認してください。主な成果物は次のとおりです。

- `summary.json`: 実行・受理状態の要約
- `experiment_report.md`: 読みやすい実験報告
- `results.xlsx`: 集計と照合用の表
- `rolling_hourly_chain/executed_day_accounting.json`: 受理済み Rolling の最終費用正本

`job completed` だけを成功や研究成果として扱わないでください。

## 研究用の正式実行

通常の試行計算と正式研究実行は意図的に分けています。試行計算は診断用であり、dirty な Git worktree でも動かせますが、成果物は研究公開 `BLOCKED` のままです。

正式実行では、少なくとも次を満たす必要があります。

1. clean な worktree と固定した Git SHA から開始する。
2. 運行日、時刻表、営業所・路線、車両、初期状態、充電器、BESS、料金、ソルバー条件を明示して Prepare する。
3. 日初計画、全時間帯の Rolling、独立物理検証、実行日会計、成果物照合をすべて通す。
4. PV 比較では、PV 曲線以外の対照条件をハッシュで一致させる。

具体的なコマンド、必須証跡、失敗時の表記は [正式研究実行の手順](docs/notes/FORMAL_RUNBOOK_CURRENT.md) を正本とします。最新の未解決事項は [研究リリースのブロッカー一覧](docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md) で確認してください。

## よくある確認ポイント

### データが利用できない

まず画面または `GET /api/app/data-status` でデータ状態を確認してください。`BUILT_DATASET_REQUIRED` が出た場合は、データを推測で補わず、[運用ガイドのデータ復旧手順](readme_operation.md#no-module-named-tokyubus_gtfs)に従ってください。

### 503 またはジョブ待ちになる

BFF は同時に一つの実行しか受け付けません。前のジョブの終了を待つか、比較実行には [運用ガイド](readme_operation.md#1-ソルバーモード比較benchmark) の順次実行スクリプトを使ってください。

### `INFEASIBLE` になる

SOC、初期状態、車両台数、充電器・契約電力、回送接続、`allowPartialService` を確認し、条件を変えた後は Prepare からやり直してください。制約を緩めたり、時刻表を勝手に加工したりして解を作ることはしません。

## 関連資料

| 読者・用途 | 資料 |
| --- | --- |
| 日常操作・比較・トラブルシューティング | [運用ガイド](readme_operation.md) |
| 指導教員・共同研究者向けのモデル説明 | [教員レビューガイド](README_core_professor.md) |
| 定式化と実装状況 | [制約・目的関数の定式化](docs/constant/formulation.md) / [実装状況](docs/constant/implementation_status.md) |
| 車両セットを固定する研究契約 | [Scenario Fleet Contract](docs/model/SCENARIO_FLEET_CONTRACT.md) |
| 図表・生データの対応 | [Literature Figure Mapping](docs/model/LITERATURE_FIGURE_MAPPING.md) |
| React + FastAPI、その後の Tauri 移行 | [frontend 移行仕様](docs/frontend/README.md) |
| 実装の変更履歴・検証結果 | [開発ノート](DEVELOPMENT_NOTES.md) |

## リポジトリの見取り図

```text
run_app.py                  Tkinter + FastAPI をまとめて起動
tools/scenario_backup_tk.py 現行の操作画面
bff/                        FastAPI BFF と run の最終化
src/                        配車・最適化・検証のコア
data/                       入力データと built dataset
output/                     実行成果物（Git 管理外）
docs/                       研究・運用・移行の詳細資料
tests/                      回帰テスト
```

## 開発・検証

開発環境では `pytest` を追加してから、少なくとも次を実行してください。

```powershell
python -m pip install pytest
python -m compileall -q src bff scripts tools
python -m pytest -q -p no:cacheprovider
```

README の入口とリンクだけを確認する軽量テストは次です。

```powershell
python -m pytest -q tests/test_readme_navigation.py
```

研究計算の意味、制約、受理ゲートに影響する変更では、README だけで説明を完結させず、該当する runbook・開発ノート・ブロッカー資料も同時に更新してください。
