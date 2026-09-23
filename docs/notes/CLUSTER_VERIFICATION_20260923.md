# 分散計算の検証記録 — 2026-09-23

## 範囲と判定

Phase 0 は [監査記録](CLUSTER_PHASE0_20260923.md)。確認対象の
`5d790ea16329eda22e3ceb9930548f9d33de1bb3` はローカルmainの祖先。
作業中にmainは `c98f792b25ffe90bcd3f4827240f1d06dd87a1ec` へ進んでおり、
その既存作業と未commitの研究変更を保持している。

**実行基盤の試験と研究採用は別。正式7日運用の受入は引き続きBLOCKED。**
非Gurobi ALNSは `candidate_only` に相当する明示的な診断profileである。
既存ALNSからexact repairを除くため探索手順が異なる。最適性・解品質の同等性は主張しない。
初期対応はcanonical ALNS・1日・BESSなし・daily-return契約なし・rollingなし・研究採用なし。
未対応の組合せはPrepare/投入前に拒否し、既存の研究gateを緩和しない。

## 実際の証拠

- 旧固定診断版 `a23e7592a75db820c42d0b1e196cf1295e07df08`：
  親機とWindows従機11台へ独立12ケースを配置し、**12/12のCOMPLETED・回収・hash検証**。
  月ごとに架空の1日・4便を用いた30秒のPhase 3診断であり、12カ月の連続計算ではない。
  `output/cluster-deployment/monthly-audit.json`、`monthly-v4/status.json`、`monthly-v4-resume.log`。
- 同じ旧成果物のSOCイベント出力には、効率・上限制約・帰庫消費の不整合が残る。
  旧成果物を修正後コードの証拠として流用しない。数値はDIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。
- 新コード・親機Windows：`no-gurobi-native-guard-v2` と `no-gurobi-absent-v2`。
  実際のPrepare→BFF→canonical ALNS→検証→成果物作成を通過。
  Env=0、Model=0、optimize=0、forbidden=0。後者ではimport finderでgurobipyを利用不能にした。
  物理可行性・正式研究採用・7日間の完全性の証明には用いない。
- 新管理層・親機の実WLS：`managed-license-v2/managed-license-smoke.json`。
  共有枠取得後にEnvを1回起動し、2モデルを直列求解。目的値は各1.0。
  1つ目を早期disposeした後も終了処理が成功。モデル解放→Env解放→330秒の予約保持。
- 最新 `cluster-final-267.log`：Python **267通過、skipなし**。配布ZIPを明示し、
  Windows PowerShell 5.1の実プロセス検査も含む。既存依存ライブラリの非推奨警告2件。
  `frontend-final-ui-tests.log`：画面 **23通過**。`frontend-final-ui2-build.log`：TypeScript/build通過。
  API型生成は `frontend-final-checks.log` に記録。過去の235件/17skip、259件は中間結果。
- 新固定版 `62112fe2a790ee5f31e33ea153cb4b56de7047b9`：親機＋従機10台へ12個の独立診断を
  自動割当し、12/12完了・回収。`no-gurobi-v5-batch-audit.json` が全件のGit、入力bundle、
  source、ZIP、必須104成果物のhash一致、Env/Model/optimize/forbidden各0、counts_completeを確認。
  **12件とも `terminal_soc_balance_failed`、teacher_release_status=BLOCKED**。
  配置・実行・回収の成立を示す。物理可行性・研究承認を示さず、費用比較には使わない。
- v5配置照合：`staging-v5-retry/report.json` の11台が同じGit/source/uv.lock/runtime/8datasetでVERIFIED。
  `LAPTOP-A709UNA0` は今回Tailscaleオフラインのため新版未確認・投入無効。旧版の成功で代替しない。
- v5 controllerを全タスク終了後に再起動し、同じbatch/stateで再開。
  `resume-after-controller-restart.log`：12件の同じjob IDを引継ぎ、キュー総48件は増えなかった。
  これは完了後の再起動検査であり、実求解途中の強制電源断試験ではない。

## T01–T32

「mock」は単体/モック試験。Windows実機には親機だけの実プロセス検査も含むため対象を明記する。
「未」は未実施でありPASSではない。旧版の試験は新版の実機合格に置き換えない。

| ID | mock・ローカル回帰 | Windows実機 | Gurobi実機・残る範囲 |
|---|---|---|---|
| T01 | seed validation、重複IP/node/self識別、初回投入無効 | 既存登録11台は保持 | 新規端末の本人/host key確認は別途必要 |
| T02 | UNKNOWN/stale/未検証端末の投入拒否 | 親機probe | 障害の全組合せは未 |
| T03 | Tailscale欠如をUNKNOWNとする | 既存全台到達の旧証拠 | 新版の実断線は未 |
| T04 | SSH port/auth/host key/timeoutを分離 | 旧版11台SSH認証済み | 故障を実端末へ注入していない |
| T05 | Tailscale JSON欠損/型変更を拒否 | 親機parser | provider形式の将来互換性は保証外 |
| T06 | 通常probeはimport/versionのみ、Env guard | 親機native subprocess | license testだけ明示求解 |
| T07 | exact repairの候補/重み/予算0、禁止guard | 親機のPrepare禁止guard/ライブラリ不在、v5の11台12件回収 | Env0/optimize0、1日診断限定 |
| T08 | 旧経路/rolling/BESS/研究との不適合拒否 | 親機E2E | 汎用BESS非Gurobi実装は未対応 |
| T09 | 未知mode/profileの拒否 | — | 黙示HYBRIDへ落とさない |
| T10 | 10競合要求で2枠、外部予約込み | 親機2モデル直列 | 新版全台での同時WLS負荷試験は未 |
| T11 | license失敗は専用分類、再Env起動抑止 | 親機成功経路 | 実契約の失効は意図的に起こしていない |
| T12 | Env再利用/解放順/永続token tail | 親機WLS 1Env/2solve | providerの外部利用量は推定しない |
| T13 | LOST枠保持、永続backoff、照合の排他 | 旧12件を同IDで復帰回収 | 新版実断線注入は未 |
| T14 | 同key/同hashは同attempt、変更入力は拒否 | ローカル子プロセス | 全11台の応答喪失注入は未 |
| T15 | SQLite再起動、remote PIDをlocalで参照しない | v5 controller再起動後、12件同ID・重複0 | 実求解中のOS再起動は未 |
| T16 | PID creation identity不一致を別プロセスとする | 親機Windows API | PIDだけで所有権を判断しない |
| T17 | 独立runner/Windows breakaway経路 | 旧版SSH切断後に全台計算継続 | Electron強制終了/従機再起動は未 |
| T18 | drain/登録取消/所有attempt停止、終了まで予約保持 | 親機callback mock | 実Gurobi長時間求解の中断は未 |
| T19 | attempt別出力・retry新ID・同hash再取得 | v5の12件個別ZIP | 同一scenario多seedの実機負荷は未 |
| T20 | code/input/dataset/runtime/uv.lock改変拒否 | v5の11台配置照合と12件回収hash確認 | 違うSHAの結果を再ラベルしない |
| T21 | dirty/stale正式実行拒否を回帰 | 親機Git検査 | 今回正式実験なし |
| T22 | ZIP traversal/衝突/SSHオプション拒否、link/junction拒否 | WinPSの一時領域で検査 | 未登録hostへ投入しない |
| T23 | UTF-8とencoded PowerShell | 親機の日本語・空白pathでnative round-trip | 全11台での同名path試験は未 |
| T24 | 完了と研究gateを分離、失敗理由を保持 | v5全12件の期末SOC未達/BLOCKEDを回収・画面表示 | 研究採用不可 |
| T25 | 既存Phase/gap/artifact契約を回帰 | 旧Phase 3小規模求解 | 統合総費用大域最適を主張しない |
| T26 | 7日入力hash/最終window/rolling状態の既存契約維持 | 連続168回の新版実行は未 | 正式multi-dayはBLOCKED |
| T27 | 12件投入の応答喪失/再開、失敗seedも分母・理由保持 | v5実batch CLIの投入→回収→監査→再起動後再開 | 求解完了率と研究gate通過率を分離 |
| T28 | 通常/再最適化wrapperとclusterの共有license/CPU枠 | 親機の実WLS管理経路 | BFF外の任意スクリプトは管理対象外 |
| T29 | Prepare revision/未保存フォーム/既存結果/API型、23画面テスト | build/ブラウザーで12件のSOC未達・Env0表示 | Electron実ウィンドウの再起動は未 |
| T30 | 更新失敗でもRUNNING履歴を表示、stale警告 | UI通信失敗をモック | 実端末停止と混同しない |
| T31 | hash不一致/途中書込/ZIP copy disk-fullで未公開 | 親機ファイルI/O | 従機rawを保持。物理disk-fullは未注入 |
| T32 | ACTIVE/RECONCILINGは時間で解放しない | 親機broker再オープン | remoteの終了確認前は保留 |

## 自己レビュー・未解決

修正した問題：通常実行の枠迂回、auto threadsの過小予約、取消済み成果物の回収漏れ、
同attempt照合競合、回収途中の公開、SOCイベントの充電効率/最大SOC/帰庫消費、UI再送重複。
SOC出力は再構成由来と明記し、solver-native系列に偽装しない。目的関数・制約を変更して
費用を合わせたものではない。広範なrolling SOC系列の同等性は今回の診断だけで承認しない。

独立レビューは未取得。claude code/開発担当者によるレビューと、別途承認されたclean commit正式実行が
必要であり、今回の自己レビュー・配置成功を研究承認へ昇格させない。
外部Gurobiアプリ、手動電源断、OS更新再起動、バッテリー切れの制御は保証しない。
各PC1ジョブ、RAM要求・OS余裕・AC条件・最新telemetryで投入を抑える。

## 機械的な運用

`tools/cluster/release.py package/stage` → 固定版controller →
`synthetic_batch.py`（配置試験のみ）または利用者のbatch manifest →
`batch.py check/run/status` → `audit_batch.py`。すべて通常のPython/PowerShellプログラムで、AI APIを呼ばない。
private config、資格情報、研究データの自動外部送信は行わない。
詳細は [運用手順](../DISTRIBUTED_COMPUTE.md)。

## 12:30 JST 引渡し時点の版と起動

- controller/workerの実計算コードは上記v5のまま凍結。診断snapshotはmainの未commit作業を
  独立Gitへ写したものであり、正式研究release承認ではない。
- `synthetic_batch.py` は凍結後に、scopeを保存してからPrepareする順序と、cwd変更前の出力path確定を修正。
  旧helperは最初の投入でprepared hash不一致として拒否された。元入力を書き換えて通さず、新しいbatch IDで
  正しくPrepareした。成功した12件は修正済みmainのhelperから投入している。
- `audit_batch.py` とHTTP拒否を永続stateへ残すCLI改善もmain側。運用CLIはmainの
  `tools/cluster/` を使い、v5に同梱された旧helperをコピーして使わない。
- UIはv5 backendと別の `frontend-v5-ui2/`。`frontend-v5-ui2.sha256.json` に3assetのhashを保存。
  期末SOC未達と実Gurobi利用回数を履歴に表示し、狭い画面のnavにaccessible nameを追加。
  IABで12行の未達理由・Env0/求解0を確認。バックエンド/最適化出力は変更していない。
  319px幅でもファイル/検索入力欄を収め、ページ幅304px・はみ出す入力0をDOM/描画で確認。
- 回帰後にmainのsolver_adapterの行末空白1個を除去し、変更前後のAST一致を検査した。
  凍結版のバイト列・SHAは保持。CRLFは `cr-at-eol` を指定して差分検査する。
- `output/cluster-deployment/START_CLUSTER_V5.cmd` は前景controller起動、
  `RESUME_12_MONTH_CHECK.cmd` は同じ12件の再開/再監査。AIも資格情報入力も不要。
  controller起動中は2つ目を起動しない。URLは `http://127.0.0.1:8868/`。
- 隠しウィンドウでの常駐起動は自動承認レビューが拒否（詳細理由なし）。前景起動で検証済み。
  OSサービス/タスクスケジューラへの自動登録は行っていない。
- 公開候補92ファイルをprivate inventory/WLS秘密値と突合し、混入0。
  private config/output/指示書フォルダのGit除外を確認。`cr-at-eol`付き対象差分検査は通過。
  GitHub push、mainへの一括commit、有料CIの有効化は行っていない。

## 15:00 JST 旧レビュー再監査の追加証拠

- T15/T16: 画面用ジョブ記録でもWindowsの読取専用生成時刻照会を使用。PID再利用、権限不明、遠隔PID除外をmock確認。親機Windowsの現PID照会は実機確認。11台での故障注入は未実施。
- T15/T31: 破損JSON、読込拒否、復旧保存失敗、disk-full相当の置換失敗で元記録を保持。別process同時更新は両方のmetadataを保持し、`state_version`を2へ増加。画面用JSONの破損がSQLiteキューのmirror処理を止めないことをmock確認。
- T06/T07: no-Gurobi profileの直接部分MILP呼出し拒否と、部分MILP下位TimeLimit/研究実行制御の継承をmock確認。新SHAの実Gurobi・正式7日モデルは未検証。
- 試験: 分散・ALNS関連172 passed / 17 skipped、BFF等54 passed、最終復旧/ALNS/画面関連75 passed。各集合は一部重複し、単純合計を独立件数としない。
