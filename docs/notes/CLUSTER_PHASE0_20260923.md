# 分散計算 Phase 0 監査・変更計画

日時: 2026-09-23 JST。状態: 実装前の再監査。研究承認ではない。

これは開始時点の記録。後続のmain更新・実装・実機試験は
[検証記録](CLUSTER_VERIFICATION_20260923.md) に追記しており、以下の不足を現在の未修正状態とは扱わない。

## 基準と既存作業

- 指示書確認SHA: `5d790ea16329eda22e3ceb9930548f9d33de1bb3`。
- ローカルmain HEAD: `9ff2285ff27dd6a177956033b73dbe61fcd3dcc5`。前者は後者の祖先。既存研究変更23ファイル、963追加/174削除に加え、未commitのcluster/UIと研究資料がある。古いmainには戻さない。
- `AGENTS.md`を読み直し、ユーザー提供指示書とprivate seed全11台のスキーマを確認した。指示書は旧SHAに対する提案で、現在の接続証拠より古い。seedの初期未確認値で実機検証済み設定を上書きしない。
- private seed・指示書は実アドレスを含むためフォルダ全体をGit対象外にした。公開文書にはアドレス・資格情報を複製しない。
- 別ディレクトリの固定診断版 `a23e7592a75db820c42d0b1e196cf1295e07df08` で12カ月配置試験が進行中。今回の改修はその実行コードを変更せず、新版の証拠には流用しない。

## 実際の呼出し経路

| 入口 | 現在の経路・観察 | 改修点 |
|---|---|---|
| App / Workspace / RunPanel | pagesと既存state、Prepare revision確認、通常run APIまたはcluster API | 全体管理画面を再利用。未保存フォームを保持 |
| 通常run-optimization | `enqueue_optimization` → `_submit_optimization_job` → executor → `_run_optimization` | 現在cluster枠を迂回。共有資源予約を追加 |
| cluster/jobs | 同じenqueueのpreflight → `freeze_optimization` → SQLite → runner → `_run_optimization` | prepared実体・外部入力・Git検査は既存を維持 |
| canonical ALNS | OptimizationEngine → ALNSOptimizer → repair候補 → `partial_milp_repair` → MILPOptimizer | 禁止profileのとき候補と重みから完全除去 |
| canonical充電評価 | repairの`_with_recomputed_charging`とengine finalizer内の充電再計算・SOC修復・CostEvaluator | 数値意味と非求解性をguardで検証。候補生成と研究解を区別 |
| 旧ALNS | `src/pipeline/solve.py` → `src/solver_alns.py:evaluate_assignment` → availability Env → 内側LP Model | 非Gurobi profileの未対応経路は事前拒否。暗黙fallbackに依存しない |
| MILP / Phase 3 / Phase 4 | MILPOptimizer → solver_adapter。Stage 1/2、seed、root relaxation、exact clique、fixed recourse、path-source追加モデル | 同一実行の直列モデルへ共有Envを注入。追加求解もカウンタ対象 |
| rolling / reoptimize | BFF再最適化executor / rolling_chain → RollingReoptimizer → OptimizationEngine。充電毎時はMILP | run全体を予約。非Gurobiとの未対応組合せを事前拒否 |
| capabilities / probe | 現在のBFF capabilitiesは静的応答、cluster probeはimport/versionのみ。`is_gurobi_available`自身はEnv.startを呼ぶ | 通常監視はEnv0を強制試験。ライセンス試験を明示jobへ分離 |
| legacy報告・simulation | pipeline report/simulate/sensitivityにもmodel.optimizeがある | CPU-onlyの表示名だけで0枠分類しない |

`src/`と`bff/`全PythonをAST解析し、Env/Model/optimize/availability入口を記録した。
28,000行を超えるsolver_adapterも全文を構文解析し、追加モデルの所属関数を列挙した。
動的到達の完全性はこの静的走査だけでは証明せず、禁止guardと実行カウンタで検証する。
ローカル監査原本: `output/cluster-deployment/full-gurobi-call-audit.json`。

## 確認された不足

1. 現行ALNSのexact repair下限は1回/10秒で、明示的な非Gurobi設定がない。
2. clusterの2枠はjob数ベースで、通常ローカルAPI・再最適化を包んでいない。availability専用Envと暗黙default Envも集約されていない。
3. workerの同ID再submitは既存ディレクトリエラーになり、同hashを同launchとして返す冪等性がない。retryは新job IDで隔離されるが、attempt/fencingが明示されていない。
4. 再起動はLOSTとして予約を保持するが、稼働中workerへの継続的な再接続と回収には不足がある。
5. RAM予約・stale拒否はあるが、候補は登録順。実測性能による選択がない。
6. private提案スキーマのimporterがない。実機設定を初期化し直すことなく、新規importだけ未確認・投入無効で登録する必要がある。
7. 旧固定診断の追加監査ではSOCイベントCSVとソルバーSOC系列に不整合がある。配置実行成功を研究/物理出力全体の承認にしない。

## profile分類と制約

| profile | Gurobi | 初期の主張範囲 |
|---|---|---|
| 既存mode / ALNS exact repair / MILP Phase 1–4 / hybrid / rolling | required、共有予約 | 従来の個別研究gateを維持 |
| `alns_no_gurobi_v1` | forbidden、Env0/optimize0/exact repair0 | canonicalの検証済み組合せのみ。初期はcandidate_only、研究採用不可 |
| diagnostic / monitoring | forbidden | 実機情報・配布検証のみ |
| license_test | required、明示要求・予約 | 小規模求解によるライセンス確認のみ |

非Gurobiで未検証の旧ALNS、rolling、BESS評価、daily-return、formal research組合せは投入前に拒否する。既存profileの既定挙動と探索回数は変更しない。新profileを既存ALNSの研究結果に混ぜない。

## 変更順序と対象

1. **登録・性能割当**: `contracts.py`, `worker_registry.py`, `worker_monitor.py`, 新規private importer/resource policy、ClusterPanel/WorkerNodes。実測CPU/RAM/diskと同profile実行履歴で選択。研究threads/time limitは保持し、不適合端末を除外。性能不明を高速と推定しない。
2. **キュー寿命**: `store.py`, `scheduler.py`, `runner.py`, `artifacts.py`。idempotency key/attempt/generation、同hash再submit、PID creation/boot identity、controller再接続、cancel/drain、atomic回収。
3. **solver policyと共有予約**: 新規`src/execution/solver_access.py`、`gurobi_runtime.py`、BFF通常/再最適化/worker入口。コアからBFFをimportしない。全Modelの直列Env再利用、カウンタ、永続reserved/active/releasing/release_uncertain/released。
4. **非Gurobi ALNS**: DTO→保存/Prepare→OptimizationConfig→ALNS→結果のprofile一貫性。exact repair禁止、guardによる隠れた求解検出。全経路を包めない旧入口は移行中に明示拒否。
5. **API/UI・試験**: 既存`/api/cluster`と生成型を再利用。profile/予約/attempt/割当根拠/研究gate/ログと成果物を表示。T01–T32の自動テストと記録。

既存API: workers一覧/詳細/probe/enable/disable/drain/diagnostic、jobs投入/一覧/詳細/cancel/retry/reconcile/artifacts。追加予定はprivate seed import、共有resources、batch、events/ログpagination、明示license test。意味が重複するAPIは作らない。

## 継続・停止とライセンス

UI/BFF終了後は新規割当停止、受理済み独立workerは継続、次回起動で照合・回収する。現在のWindows breakawayは実SSH切断後の継続を確認済みだが、Electron終了/OS再起動/新supervisor版の実機試験まで同一証拠に数えない。remote PIDを親機のPIDとして検査しない。

現在の実Academic WLSは本人ログインで2セッション/2026-10-19期限を確認済み。指示書の未確認値と区別する。今回の新しい管理層では通信断・controller再起動によって予約を解放しない。token durationの根拠と停止証拠が不明ならrelease_uncertainを保持する。外部provider使用量は内部予約数から推定しない。

## T01–T32の初期対応表

以下は再監査開始時点。既存テストの部分一致を新要件全体のPASSにはしない。新版のmock、Windows実機、Gurobi実機は別列で追記する。

| ID | 既存証拠/不足 |
|---|---|
| T01 | seed importerとlocal重複identity検査を追加 |
| T02 | UNKNOWN/stale拒否テストあり。seed初期値を追加 |
| T03 | tailscale故障UNKNOWNテストあり |
| T04 | SSH成功/runner欠如テストあり。port/auth/keyの分類を追加 |
| T05 | 欠損・形式変更parserを追加 |
| T06 | probeはversionのみ。11台Env0 guardを追加 |
| T07 | 新規非Gurobi E2E必須、未実装 |
| T08 | 禁止policy/充電/legacy/rolling拒否を追加 |
| T09 | modeの黙示HYBRIDを入口で拒否 |
| T10 | cluster 2枠/CPU診断並行あり。全管理経路へ拡張 |
| T11 | license失敗分類/backoffを追加 |
| T12 | cooldown再起動/設定変更テストあり。Env寿命の証拠を追加 |
| T13 | LOST予約保持あり。RECONCILING自動照合を追加 |
| T14 | 同attempt同hashの再submitを追加 |
| T15 | SQLite復元/remote PID隔離を拡張 |
| T16 | PID creation identityあり。boot/generationを追加 |
| T17 | 旧版SSH切断継続は実機証拠あり。新版/Electronは未確認 |
| T18 | drain永続化/queued cancelあり。所有process cancelを追加 |
| T19 | job単位隔離あり。attempt/同scenario seedを拡張 |
| T20 | bundle/code/dataset/hash拒否テストあり。lock hashを追加 |
| T21 | clean/stale正式拒否あり。新版profileで回帰 |
| T22 | zip traversal/SSH option拒否あり。junction含め確認 |
| T23 | 実機UTF-8出力あり。日本語/空白pathの自動試験を追加 |
| T24 | COMPLETEDと研究gate分離あり。全理由保持を回帰 |
| T25 | Phase 3統合最適性なし。候補差/gap表示を回帰 |
| T26 | 7日入力hash/最終window試験あり。formal multi-dayはBLOCKEDを維持 |
| T27 | 宣言batch/失敗分母/統計を追加 |
| T28 | 通常ローカル/再最適化が未統合、優先修正 |
| T29 | RunPanel/ClusterPanel/WorkerNodes 12 testsとbuildの旧版証拠。新版を回帰 |
| T30 | stale表示あり。UI停止/worker継続を別検証 |
| T31 | hash失敗時未確定あり。中断/disk-full再回収を追加 |
| T32 | LOST予約保持あり。永続license不確実性を追加 |

正式研究実験、独立レビュー、OS再起動・Electron強制終了の実機障害試験は未承認/未実施のまま区別する。mockは通常テストで実施し、実機操作は既存承認の範囲を超えない。
