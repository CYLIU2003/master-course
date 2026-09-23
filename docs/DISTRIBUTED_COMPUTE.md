# 分散計算の使い方

## 新規子機候補2台への初期設定ZIP（2026-09-23）

`LAPTOP-BOLC6VIT / pslab / 100.65.118.103` と `LAPTOP-8JS4DQCD / pslab / 100.87.44.64` 向けに、2台専用登録表を含む `output/cluster-deployment/onboard-20260923-add2/cluster-worker-access-setup-add2-20260923.zip` をTailscaleで送信した。ZIPのSHA-256は `6ebe69e70a3523294c45efe6fca0fc0784f6e5cce023364cf311558ddd9bcde5`。公開鍵だけを含み、秘密鍵・Gurobi資格情報は含まない。

各子機で `tailscale ip -4` と指定IPを照合し、Windowsの `pslab` でZIP全体を新しいフォルダへ展開する。そこで `SETUP.cmd -ValidateOnly` を実行し、登録名とユーザーの確認が通ってから `SETUP.cmd` を実行する。`pslab` が管理者アカウントの場合は「管理者として実行」を使う。親機からのSSH認証確認とworker登録は、その結果を受けて別途行う。Tailscale送信CLIは2台とも成功を報告したが、受信側での実行と計算環境の準備は未確認。

## 渋24の架空4便による12台疎通試験（2026-09-23）

旧渋21〜23の長時間診断は利用者指示で停止し、元の出力を保持した。新しい短時間試験は既存のPrepare→BFF→永続キュー→worker→成果物回収を使う。`synthetic_batch.py --dummy-route 渋24 --one-per-worker` は、12台すべてが有効な時に、各月1日の架空4便を1台へ1件ずつ割り当てる。1台がオフラインの初回は、12件をPrepareした後、稼働中11台へ11件だけを固定割当した別manifestを使った。停留所、10 km距離、車両、時刻はすべて試験値で、公式の渋24ダイヤ、研究用fleet、PV/BESS結果を表さない。BEV終端は既存BFFの`return_to_initial`が実効条件で、期末SOCと独立物理検証の結果を成果物で必ず確認する。

固定版の配置・source/runtime/dataset hash照合が済んだworkerにだけ投入する。当初1台がオフラインだったため、その端末を投入無効として残し、11台の結果を12台成功と報告しなかった。回線復帰後、同じ固定SHAで当該端末をstageし、未実行の固有caseだけを別batchで実行した。Gurobiなしprofileを使い、Env起動回数と求解回数が0であることを `audit_batch.py` で確認する。既存の旧12ケース、週間研究結果と混ぜない。

初回の11件は配布・回収・ハッシュ確認が全件通ったが、`terminal_soc_balance_failed` で計画受理は0件だった。入力は当初`minimum_only`としたものの、既存BFFは比較のためBEVを`return_to_initial`に強制する。SOCイベント上は初期80%→最終80%で、ALNS計画がMILP専用の終端判定メタデータを出さず、物理再計算の合格を結果へ引き継げていないことが原因だった。BEV条件を緩めて採用する代わりに、独立FeasibilityCheckerが全制約を通した時に限り、ヒューリスティック結果の欠落フラグを補う修正を別固定版にする。初回11件は新条件の成功件数へ混ぜない。

修正版`2e2333b3`を新しい固定配置へ配布し、先行11件と復帰した12台目の固有1件すべてで4便充足・独立物理検証・160→160 kWh・Gurobi利用0を確認した。回収hashと原本照合を含む詳細は[渋24ダミー分散試験](notes/SHIBU24_DUMMY_CLUSTER_20260923.md)。正式研究採用はBLOCKED。

追加4台は別枠で監視登録した。既存の`output/cluster-worker-access-setup-v3.zip`と、今回の登録表`output/cluster-deployment/onboard-20260923/workers.add4.json`、置換手順`README-ADD4.txt`をTailscaleで各端末へ送信した。ZIP本体は旧11台用のままなので、**展開したフォルダ内の`workers.json`を別送の登録表で置き換えてから**`SETUP.cmd -ValidateOnly`、次に`SETUP.cmd`を実行する。新しい`POWERSYSTEM`では`tailscale ip -4`が`100.107.38.117`であることを先に確認する。同名の旧登録PCは`100.88.215.76`。現時点で4台とも公開鍵認証拒否のため、監視のみ・投入無効であり、固定版配置や実計算は行っていない。Tailscale転送の成功をSSH準備完了とは扱わない。

親機の監視画面は `tools/cluster/install_resident_monitor.ps1 -Settings <固定版settings.json>` で現在のWindowsユーザーのログオンタスクへ登録し、直ちに起動する。固定版のclean SHAを起動前に検査し、127.0.0.1だけで待ち受ける。ログオン時に `/#cluster` を開き、画面はworkerを4秒ごと、jobを3秒ごとに更新する。閉じたブラウザは同URLから再表示でき、controllerは独立して動く。登録解除は `Unregister-ScheduledTask -TaskName MasterCourseClusterMonitor -Confirm:$false`。この常駐はAI監視や自動メールを行わない。キューに残る旧待機jobを起動前に確認し、意図しない計算を再開させない。

**最新の運用は末尾の「現行運用（2026-09-23）」と
[T01–T32検証表](notes/CLUSTER_VERIFICATION_20260923.md)を参照してください。**
途中の日付付き検証記録は当時の状態です。現在は新版で元の親機＋従機11台の実行・回収を確認済み。追加4台は別途監視のみです。
12診断すべて期末SOCの研究gateは未達であり、正式7日運用の承認ではありません。

親PCのキューから、独立した最適化ケースをローカルまたはSSH接続先へ配布します。
一つのMILPを複数PCへ分割する機能ではありません。React → 既存BFFの入力検証 →
永続キュー → 共通worker runner → 既存 `_run_optimization` → 既存reporting finalizer
という経路を使用します。子PCでPrepareをやり直しません。

## セットアップ

1. 親PCで `config/cluster/workers.example.json` を
   `config/cluster/workers.local.json` にコピーします。このローカル設定はGit対象外です。
2. 子PCに同じコミットのリポジトリとPython環境を用意します。親と同じPython、
   gurobipy、numpy、pandas、scipy、pydanticのバージョンを使います。
   実行に使う `data/built/<dataset>` も同じ内容・同じ相対配置で配置してください。
   Gitだけではignoredの研究データは同期されません。
3. 親PCのOpenSSH設定に子PCの接続先・ユーザー・鍵を登録します。例:

   ```text
   Host mc-worker-01
       HostName <子PCのホスト名またはVPN内IP>
       User <計算用ユーザー>
       IdentityFile ~/.ssh/master_course_cluster
       IdentitiesOnly yes
   ```

   `ssh mc-worker-01` で接続先のホスト鍵を確認し、known_hostsへ登録してください。
   自動実行は `BatchMode=yes` と `StrictHostKeyChecking=yes` を使用します。
   秘密鍵・パスワードは画面やworker設定JSONへ書きません。
   Windows子PCでは通常のOpenSSH Serverを別途設定します。
4. workerの `host` にSSHのHost別名、`repo` にリポジトリ、`python` にPython実行ファイル、
   `workspace` にジョブ保存先の絶対パスを設定します。
   Windows子PCは `shell: "powershell"`、Linux子PCは `shell: "posix"` です。
   例のSSH workerは安全な初期状態として `enabled: false` です。準備後にtrueへ変更します。
5. `slots` はそのPCの同時ジョブ数、`ram_gb` は使用するPCのRAM容量です。
   最適化に使うPCはライセンスを確認して `gurobi: true` にします。
   `global_gurobi_slots` は契約上利用可能な**クラスタ用の同時実行枠**を設定します。
   ライセンス数を自動推定しません。上限・既定値は2です。
   通常のBFF実行・再最適化・明示ライセンス試験も同じSQLite予約を使用します。
   アプリ外のスクリプトや別アプリは `external_gurobi_slots` で予約してください。
   provider上の使用量を内部予約数から推定することはできません。
6. BFF/Electronを再起動し、「分散計算」→「接続確認」→「診断タスクを配布」を実行します。
   診断はソルバーライセンスを消費せず、実行・回収・履歴保存を確認します。
   接続確認はGurobiの導入バージョンを報告しますが、ライセンスの有効性までは検査しません。

設定ファイル未作成時はこのPCの診断workerだけを登録します。
設定場所は `MC_CLUSTER_CONFIG`、親機のキュー保存先は `MC_CLUSTER_DIR` でも指定できます。
同じ保存先を使うBFFは1プロセスに限定され、OSのファイルロックで二重起動を拒否します。
実行中・LOSTのworkerについては、解決するまで同じIDの接続先やworkspaceを変更しないでください。

## 実行と結果の受け取り

「実行」画面で保存済み条件から入力を準備し、「計算の配布先」で自動割当またはPCを選びます。
分散経由の最適化は診断用途でもclean commitを要求します。現在の変更をレビュー・コミットした後、
同じコミットを各PCへ配置してBFFを再起動してください。実行中にコードやdatasetを更新しません。
正式研究実行は従来の追加ゲートも必要です。

配布は、prepared入力の**元バイト列**、シナリオの入力スナップショット、確定したsolver引数を凍結します。
manifestにはGit SHA/dirty状態、PythonコードのSHA-256、環境バージョン、入力bundleのSHA-256を保存します。
子機ではdatasetファイル一覧・各SHA-256も比較し、計算前後に入力とコードを照合します。
ソースの改行コードを含めてバイト一致を要求するため、異なるOSでcheckoutするときも設定を揃えてください。

親機: `output/cluster/jobs/<job-id>/`

- `manifest.json` / `bundle.json`: 凍結した条件と入力
- `transport.stdout` / `transport.stderr`: 通信記録
- `artifacts/`: ハッシュ照合済みの子機成果物
- `artifacts.zip`: 画面からダウンロードする成果物

子機: `<workspace>/<job-id>/` にmanifest、bundle、state、標準出力/エラーログ、
ジョブ専用の `output/` を保存します。元の親シナリオへ計算結果を上書きしません。
研究上の判定は成果物内の既存validation・acceptance・accountingレポートを確認してください。
クラスタの `COMPLETED` はプロセスと回収の完了であり、研究採用・最適性を意味しません。

## 再起動・通信切断

| 状態 | 意味・操作 |
|---|---|
| QUEUED | PC能力・ライセンス・空き枠を待機。登録取消が可能 |
| STAGING | 接続とコード・RAM条件の確認中 |
| RUNNING | workerへ実行を要求済み。求解完了を待機 |
| COLLECTING | 結果回収・全ファイルのハッシュ照合中 |
| COMPLETED | workerの処理完了と結果の照合完了 |
| BLOCKED | 求解開始前に接続、コード、dataset、環境などが不一致 |
| FAILED | worker内で失敗、またはプロセス途中終了を確認 |
| LOST | 終了をまだ確認できない。PC枠とライセンス枠を保持 |
| CANCELLED | 待機中の登録を取り消した |

親機再起動で待機キューと履歴は復元されます。途中のジョブはLOSTとなり、勝手に再実行しません。
LOSTの「結果を照合」は同じworkerから保存済みstateと成果物を取得します。
Windows/LinuxではPIDの作成時刻も照合し、途中終了とPID再利用を区別します。
動作中または確認不能ならLOSTを維持します。子機のstateファイル自体が失われた場合は
自動で枠を解放しません。子機と保存先を復旧して照合してください。

再試行できるのはFAILED/BLOCKED/CANCELLEDだけで、入力・コードの一致を確認して**新しいID**を発行します。
旧ジョブは履歴に残ります。実行中プロセスの強制キャンセルは未対応です。

## APIと範囲

`/api/cluster` はloopbackの接続とHost/Originに限定されます。Electronでは既存Bearer認証も維持します。
ブラウザからSSHコマンド、鍵、任意のスクリプトを指定するAPIはありません。

- `GET /workers`、`POST /workers/{id}/probe`、`POST /workers/{id}/diagnostic`
- `GET /workers/{id}`、`POST /workers/{id}/enable`、`POST /workers/{id}/disable`、`POST /workers/{id}/drain`
- `GET /jobs`、`POST /jobs`、`GET /jobs/{id}`
- `POST /jobs/{id}/cancel`、`POST /jobs/{id}/retry`、`POST /jobs/{id}/reconcile`
- `GET /jobs/{id}/artifacts`

最適化登録の例（通常の `RunOptimizationBody` のsolver条件を指定）:

```json
{
  "scenario_id": "既存のシナリオID",
  "worker_id": null,
  "minimum_ram_gb": 16,
  "request": {
    "prepared_input_id": "既存の準備済み入力ID",
    "mode": "phase3_two_stage",
    "research_run": true,
    "gurobi_threads": 2,
    "rebuild_dispatch": false,
    "use_existing_duties": false,
    "force_reprepare": false
  }
}
```

現段階は凍結済み入力からの最適化と接続診断が対象です。再最適化・シミュレーションは従来経路を使います。
外部パス指定の気象ファイルなど、未同梱のファイル依存は登録時に拒否します。
datasetの自動同期、任意コマンド実行、実行中のログ追尾、自動リトライは行いません。
全最適化ジョブはrollingやhybrid内部の利用も考慮してGurobi枠を保守的に1つ予約します。
成果物はディスク上のZip64として別ストリームで転送し、ZIP全体と各ファイルのSHA-256を照合します。
通常経路には旧方式の1 GiB制限はありません。子機・親機ともZIPと展開先の空き容量が必要です。
容量不足・転送失敗はLOSTとして保全し、照合成功まで成果物リンクを公開しません。

## 7日間対応の再点検（2026-09-22）

7日間・168時間の診断用入力を配布できるよう、`date_series_contract.pv_execution_input` の
別管理された実測PVをPrepare時のSHAで検証して同梱します。子機の専用領域へ展開し、既存の
ローリング実測PV読込に渡します。予測PV・時刻表・prepared入力のバイト列は書き換えません。
未同梱の任意パスは引き続き拒否します。

コアには `MULTIDAY_RESEARCH_BLOCKED` があり、複数日の正式研究実行は未対応です。
公開APIでもPrepare・ジョブ生成前に拒否し、画面に理由を表示します。この変更で研究採用を認めたり、
現在別worktreeで実行する週間キャンペーンの専用solver設定を自動再現したりはしません。
各独立ケースをPCに割り当てる機能です。1週間を7日に分割して状態の連続性を失わせる処理はありません。

実行画面は7日・168時間・予定168回を表示します。予定数は実測の完了数ではありません。
ローリングOFF時に `day_ahead_exploratory` を明示して前日計画のみ実行するよう修正しました。
分散計算画面には期間・シナリオ名・予定回数・待機/実行/要確認/完了の集計を追加しています。

回帰検証はPython117件（分散/週間/日跨ぎ/既存実行経路）、フロント17件と本番ビルドが通過。
7日分672点の実測PV一致、日跨ぎと最終167時から168時までの窓、改変・欠損拒否、正式実行拒否、
ディスク転送とハッシュ不一致拒否を確認しました。別PCでの週間実規模solve・168回連続完了と
独立レビューは未実施です。実ブラウザから修正後のローカル診断 `17c3b505-6bc7-4781-8776-eb2a6d665913` を配布し完了。
ダウンロードZIPのSHAもworkerの `4d5828758594a621cd6b7bcd64e5c520664af2287a54bfb2116a6fda75cc1bbb` と一致。
画面記録: `output/playwright/cluster-weekly-dashboard.png`。以下は初回実装時の検証記録で、現在のソースSHA証明ではありません。

## 検証と残る確認

2026-09-22: ローカル実子プロセスで配布・実行・回収・ハッシュ照合・履歴復元を検証。
実ブラウザで「診断タスクを配布」からCOMPLETED表示と成果物ZIPのダウンロードを確認しました。
画面記録: `output/playwright/cluster-dashboard.png`。
APIのloopback制限、スロット制御、入力改変検出、SSH引用処理、LOST復旧、
既存実行への引数引継ぎを回帰テストで確認しました。
Pythonは分散機能20件と既存経路86件の計106件、フロントエンドは全14件が通過。
TypeScript/Electronを含む本番ビルド、設定JSON検証、対象差分のwhitespace検査も通過しています。
検証記録は `output/cluster_validation/verification.json`、最終診断ジョブは
`c8d0b6cc-6f52-4a75-9472-45b34f2e4983` です。稼働コードのsource digest一致も確認しました。

別PCとの実SSH疎通・Windows/Linux子機での実求解・正式研究ゲートの通過は未検証です。
実機の接続情報を設定して、診断→小さい最適化ケース→結果照合の順に検証してください。
自己レビューでは二重実行、孤立プロセス、成果物パス、入力不一致の問題を検査・修正しました。
独立レビューと研究採用の承認は別途必要です。

## 端末管理と子機の初回設定（2026-09-22）

登録済みPCは、オンライン・SSH認証済み・環境一致・計算可能を別々に表示します。
Tailscaleのオンラインだけでは配布しません。観測失敗や期限切れは「不明」とし、
空きRAM、ディスク、Python/Gurobi、ソースとコミットの一致を確認します。
背景確認はネットワーク5秒、環境30秒、最大4台並列。観測期限は20秒/90秒です。
「受付停止」は実行中のジョブを継続し、新規割当だけを止めます。「無効化」も実行中ジョブを強制終了しません。
設定は再起動後も保持します。再起動直後は新しい接続確認が終わるまで計算可能にしません。

Windows子機への初回公開鍵登録:

2026-09-22、指定11台へTailscaleで `cluster-worker-access-setup-v2.zip` を直接送信し、
CLIで全11件の送信成功を確認しました。手動でZIPを移す必要はありません。
Tailscale 1.34以降のWindowsでは受信ユーザーのダウンロードフォルダへ保存されます
（それ以前はデスクトップ。[公式説明](https://tailscale.com/docs/features/taildrop?tab=windows)）。
まず1台だけ次の手順を実行し、親機からSSH認証を確認した後に残りへ進んでください。

1. `output/cluster-worker-access-setup-v2.zip` を子機の新しいフォルダへ全体展開します。
2. 登録されたWindowsユーザーでログインし、`SETUP.cmd` を実行します。
   管理者アカウントなら右クリックの「管理者として実行」を使います。
3. `Worker access configured:` の表示後、親機からSSH接続確認を行います。

旧版の空のPath例外は、WinPS5.1でparam既定値のPSScriptRootが空になることが原因でした。
本文で配置先を解決し、CMDでも絶対パスを渡す方式へ修正済みです。
事前確認だけなら `SETUP.cmd -ValidateOnly` を使います。
既存の公開鍵は保持し、変更時だけバックアップします。ZIPに秘密鍵やWLSキーは含めません。
WinPS5.1で日本語/空白パス、別作業フォルダ、CMD起動、鍵追加、ACL、再実行を実ファイルで検証しました。
配布ZIPの一覧/SHA/公開鍵形式と、全11登録名でのValidateOnly、誤設定時の停止を加え、セットアップ単体は22 testsが通過しました。
これはローカル検証であり、各子機での管理者実行・既存sshd設定・SSH認証の検証は残っています。

計算はSSH呼出しから独立したOSプロセスへ引き渡し、状態をファイルに保存します。
通信断や親機再起動時はLOSTとして予約を保持し、照合時に回収します。勝手な再実行はしません。
Windowsは計算中のみ自動スリープを抑止します。手動電源断、OS再起動、蓋閉じやバッテリー切れを
防ぐ機能ではありません。子機上での切断継続試験は、SSH認証後に別途必要です。

既存Academic WLSは2026-09-22のポータル確認で期限2026-10-19、同時利用2セッションでした。
親機では実認証と1変数の求解が成功しています。`global_gurobi_slots` を2に設定し、各子機1ジョブまでとしています。
WLSキーは本人の研究用途で使用し、子機上の本人専用ファイルを `gurobi_license_file` で指定します。
自動監視はGurobiのインストールだけを調べ、ライセンスを定期的に消費しません。
実ライセンスの有効性は別の実求解で確認してください。他アプリが使うセッションはこのキューから制御できません。
[Academic WLSの公式制限](https://support.gurobi.com/hc/en-us/articles/34672988479633-What-are-the-restrictions-on-using-an-academic-WLS-license)。

今回のローカル回帰はPython41件、フロント20件と本番ビルドが通過しました。
実ブラウザから独立プロセス方式の診断 `ab967ed3-8c73-4a63-bc96-b6299faf4122` を配布し、
COMPLETED・成果物回収・`idle_sleep_inhibited=true` を確認しました。
指定11台はTailscale/SSHサーバーへ到達しましたが、子機での公開鍵登録が未完了でSSH認証は未通過です。
子機の環境・WLS設置、別PC実求解、週間168回連続完了、独立レビューは未完了です。

## 並列割当と一度だけの接続検査（2026-09-22 夜）

現時点の接続検査では、登録した11台すべてがTailscale/SSHサーバーへ到達し、
SSH認証で `Permission denied` となっています。ユーザー確認でも子PCのSETUP.cmdは未実行です。
まず各PCに届いている `cluster-worker-access-setup-v2.zip` を展開し、登録されたWindowsユーザーで
SETUP.cmdを実行してください。管理者アカウントでは管理者として実行します。
公開鍵登録後にも、同じ固定ソース・Python依存環境・dataset・ライセンスの配置と検査が必要です。
接続できたというだけで最適化可能とは表示しません。

登録全台を一度だけ確認するコマンド:

```powershell
.venv/Scripts/python.exe -X utf8 tools/cluster/check_workers.py
```

結果は `output/cluster-checks/<UTC時刻>/report.json` に保存します。終了コード0は対象範囲の検査通過、
2は未準備です。最大4台を同時に検査し、AI呼出し・追加常駐監視・ソルバー実行を行いません。
`--worker <登録ID>` を繰り返すと対象を限定できます。

環境が一致した後、BFFを閉じた状態で次を実行すると、同じ永続キューを使って
ソルバー不要の診断をPC別に並列配布し、ZIPと各ファイルのSHA-256を検証して回収します。
BFF稼働中は二重コントローラーを拒否するので、画面の診断機能を使うかBFFを閉じて実行してください。

```powershell
.venv/Scripts/python.exe -X utf8 tools/cluster/check_workers.py --diagnostics --timeout 180
```

このコマンドが登録した診断だけを開始し、既存の待機中最適化を勝手に実行しません。
時間切れで実行確認が残るジョブはLOSTとしてPC枠を保持し、同じIDを照合します。
診断のPASSは分散最適化・研究採用・週間最適性の証明ではありません。

並列割当では、PCごとに全実行予約の要求RAMを合算し、最新の空きRAMから保守的に差し引きます。
STAGING/RUNNING/COLLECTING/LOSTの予約を保持するため、同じスナップショットから
複数ジョブを起動してもメモリ枠を二重使用しません。実際のOSメモリ使用を強制制限する機能ではなく、
`minimum_ram_gb` に適切な要求量を指定する必要があります。
batch CLIの最適化タスクではRAM要求の省略・0・非有限値を拒否し、APIは旧画面からの省略時に16 GBを使用します。画面の初期値16 GBは研究モデルの実測必要量を保証する値ではなく、投入前にモデルのメモリ使用量とOS余裕に合わせて設定します。

`global_gurobi_slots` は契約に基づき設定した全枠、`external_gurobi_slots` はこのキュー以外に確保する枠です。
キュー内の予約に外部予約を加え、全枠を超える最適化を待機させます。画面にも両方を表示します。
現在のローカル設定は全2枠・外部予約1枠です。月別スクリプトが動いているため保守的に1枠を確保しました。
ライセンス種別や外部アプリ使用量を自動検出した値ではありません。外部計算の終了確認後に0へ変更でき、
設定反映にはBFF再起動が必要です。ライセンス購入・契約変更はしていません。

検証: Python45件、画面12件、本番ビルド通過。ローカルの独立した2プロセスが
23:07:16〜17 JSTに重なって実行し、両方のCOMPLETEDとZIP回収を確認しました。
これは1台のPC内での実並列検証です。11台への実SSH診断・実求解は認証待ちで未完了です。
記録: `output/cluster_parallel_20260922/{fleet_check,local-parallel}/report.json`。
実行中の月別固定版 `7cb46894`、時刻表、制約、目的関数、受理基準は変更していません。
自己レビューと対象検査は完了、独立レビューは未取得です。

## 2026-09-23 更新: SSHの削除待ち復旧と全11台の認証確認

上記のSSH未認証状態は解消しました。11台すべてで親機の公開鍵による実ログイン、
sshdのRunning/Autoを確認しています。環境・WLS配置や実求解は引き続き未完了です。

LAPTOPINTEL8とDESKTOP-0SRS8PRは、鍵登録後の自動起動設定で
ERROR_SERVICE_MARKED_FOR_DELETE (1072)になっていました。Windows標準版と別導入版があり、
登録された起動先と実行中プロセスが異なる状態でした。削除を要求したプログラムは未特定です。
削除待ちは、サービス停止と開かれたハンドルの解放まで続きます。
[Microsoftの説明](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-deleteservice)。

親機から、Microsoft署名と設定検査が通る登録先バイナリを確認し、元のサービスDACLを保存。
独立したSYSTEMの一時タスクでSSHサービスだけ停止・再作成し、自動起動とDACL/権限を復元しました。
その後、新しいSSH接続、サービス構成変更のexit 0、起動先と実行中プロセスの一致を確認しました。
2つの一時タスクは解除済み。PC本体の再起動、既存鍵の再配布、Windows Updateや他サービスの変更はありません。
この11台ではセットアップの再実行は不要です。

新規セットアップ用v3は `output/cluster-worker-access-setup-v3.zip`。
サービス確認を鍵書込みより先に実行し、1072ではPC名付きで停止します。正常な自動起動設定には触れません。
WinPS5.1による配布物/キー/不正入力22件と、サービス初期化/復旧12件の計34 testsが通過しました。
`-ValidateOnly` は配布物・登録名の確認に限られ、実際のサービス復旧・SSH認証は保証しません。
`repair_pending_sshd.ps1` は管理者が対象PC名と保存先を明示して使う復旧用ツールです。
ロックが残る場合はSSHD_PENDING_HANDLESで停止し、無関係なプロセスの強制終了やPC再起動は行いません。

検証記録: `output/cluster_validation/service_final_verification_20260923.json`。
子機のPython・研究コード・Gurobiの設置、別PCでの求解、独立レビューと週間の研究採用は別途確認が必要です。
# uv環境と12カ月の配置試験（2026-09-23）

Python管理はuvを使う。`tools/cluster/environment/.python-version` は3.14.7、
`pyproject.toml` と `uv.lock` が依存関係を固定する。子機では
`UV_PYTHON_INSTALL_DIR=C:/mc-worker/python`、`UV_PROJECT_ENVIRONMENT=C:/mc-worker/venv`
を設定して `uv sync --project C:/mc-worker/bootstrap/environment --locked --managed-python` を実行する。
通常の実行はこのvenvのPythonを直接使うため、計算開始時に依存解決や更新は発生しない。
Gitは当該venv内のPATHだけで利用し、既存のPython・Git・ユーザーPATHを変更しない。

WLS資格情報はZIPやGitへ含めず、SSHで各ユーザーの `.master-course/gurobi.lic` へ配置する。
そのフォルダは当該ユーザーとSYSTEMだけにアクセスを許可する。
ライセンスの `WLSTokenDuration=5` と worker設定の `gurobi_token_cooldown_seconds=330` を対にする。
後者は終了後にも枠を保持し、キュー再開時にもジョブの固定済み設定から復元する。
解放待ち中もPCの診断ジョブは実行可能。WLS枠の外部利用は別途予約する。
[Gurobi公式の解放条件](https://support.gurobi.com/hc/en-us/articles/34567582787345-How-do-I-resolve-the-error-Too-many-sessions)。

`tools/cluster/monthly_smoke.py` は12カ月にそれぞれ架空の1日・4便を用意する。
Prepare、入力凍結、SSHの独立プロセス、Phase 3の実Gurobi、成果物ハッシュ検証を通す配置試験。
各月の連続運行や7日×12ケースの研究実験ではない。研究採用は別ゲートのまま。
uvの環境作成仕様: [公式ドキュメント](https://docs.astral.sh/uv/pip/environments/)。
# 現行運用（2026-09-23）

最新の実装・試験範囲は [T01–T32検証表](notes/CLUSTER_VERIFICATION_20260923.md) を参照。
下部の日付付き記録は当時の状態であり、現在のSSH未設定を意味しない。
登録11台のSSH/uv/Gurobi配置と、旧固定版による12ケースの実計算・回収は完了した。
12ケースは各月の架空の1日であり、12カ月連続/7日正式運用の証明ではない。

Pythonは `tools/cluster/environment/uv.lock` に固定する。例えば親機では次を一度実行する。

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.venv-cluster"
uv sync --project tools/cluster/environment --locked --managed-python
npm.cmd --prefix frontend run api:generate
npm.cmd --prefix frontend run build
```

以後は `.venv-cluster/Scripts/python.exe` で実行する。Electronもこの環境があれば優先し、
`EV_BUS_PYTHON` で既存のuv管理環境を明示できる。自動で依存関係を更新しない。

## AIなしで配置・割当・再開する

1. cleanな固定版を別ディレクトリに用意する。作業中checkoutを従機上で切り替えない。
2. `release.py package` で `.git`、追跡されたコード、指定datasetを梱包する。
3. `release.py stage` で登録各PCの `releases/<SHA>` へ配置し、同じuv runtime/lock、ソース、dataset hashを検証する。
   既存リリースを上書き/削除しない。途中失敗後は同じコマンドで再検査できる。
   全台成功時だけ新しいprivate configを書く。この段階では既存controllerを切り替えない。
4. 旧キューの実行中/LOSTを照合し、controllerを終了してから、新設定で固定版controllerを起動する。
   キューは同じSQLiteを引き継ぐ。別キューを作ってGurobi枠を迂回しない。
5. `batch.py run` が冪等投入・状態確認・hash検証付きZIP回収を続ける。中断後は同じコマンドを再実行する。

```powershell
.venv-cluster/Scripts/python.exe tools/cluster/release.py package --release C:/mc-releases/frozen --output output/package --dataset data/built/tokyu_full
.venv-cluster/Scripts/python.exe tools/cluster/release.py stage --release C:/mc-releases/frozen --manifest output/package/release.json --config config/cluster/workers.local.json --output-config output/deployment/workers.local.json --evidence output/deployment/checks
.venv-cluster/Scripts/python.exe tools/cluster/serve_controller.py --settings output/deployment/controller-settings.json --check
.venv-cluster/Scripts/python.exe tools/cluster/serve_controller.py --settings output/deployment/controller-settings.json
```

settingsには `release`, `python`, `frontend`（built dist）, `config`, `queue`, `outputs`, `port`,
`git_sha`, `source_digest`, `runtime_versions` を指定する。ソース・uv環境の差異/dirtyは起動時に拒否する。
worker認証・資格情報の初回登録は既存setup手順。配置スクリプトはOS管理者設定を変更しない。

batchは `schema_version=1`, `batch_id`, `controller_url`（loopbackのみ）, 固定版の40桁`git_sha`, `tasks`。
各taskは固有の `task_id` と `submission`（`scenario_id`, 任意の`worker_id`, `minimum_ram_gb`, 既存run `request`）。
`request.prepared_input_id` を指定し、`rebuild_dispatch=false`, `use_existing_duties=false` とする。
SHA・条件を変えるときは新しいbatch ID/保存先を使う。実行後の失敗を自動で条件変更して再試行しない。

```powershell
.venv-cluster/Scripts/python.exe tools/cluster/batch.py check output/my-batch.json --state-dir output/my-batch-state
.venv-cluster/Scripts/python.exe tools/cluster/batch.py run output/my-batch.json --state-dir output/my-batch-state
.venv-cluster/Scripts/python.exe tools/cluster/batch.py status output/my-batch.json --state-dir output/my-batch-state
.venv-cluster/Scripts/python.exe tools/cluster/audit_batch.py output/my-batch.json --state-dir output/my-batch-state --output output/my-batch-audit.json
```

`run`の終了コード0=全件計算終了、1=確定失敗を含む、2=`--once`で未完了。
HTTP 4xxなどの拒否も終了コード1で停止し、`batch-state.json`にstatus/HTTP番号を残す。
`audit_batch.py`は通信せず、回収ZIP内の入力/コード/各必須成果物hash、profile/Gurobi利用記録、
研究gateを検査する。終了コード0は回収検証の通過だけを意味し、研究承認を与えない。
各ZIPのscenario ID、prepared input ID、指定した求解制御もbatchのtaskと照合する。
全件成功でも研究承認は別。`batch-state.json` は失敗を含む分母・理由・配置先・回収hashを保持する。
投入応答を失っても同じkeyから同じjobへ復帰する。Prepareも含める場合は
`prepare_request` と `configuration_revision` が必要で、応答喪失後にrevisionが変わったケースは安全側で停止する。
確実な再開のため、本番batchには事前に凍結したprepared_input_idを指定する。

架空12ケースを用意する再現可能なコマンドもある。既定はGurobiなし・性能に基づく自動割当。
`--one-per-worker` は親機+11台への配置検査用、`--profile existing_solver_v1` は小規模Gurobi試験用。

```powershell
.venv-cluster/Scripts/python.exe tools/cluster/synthetic_batch.py --settings output/deployment/controller-settings.json --batch-id synthetic-check-01 --output output/synthetic-check-01.json
.venv-cluster/Scripts/python.exe tools/cluster/batch.py run output/synthetic-check-01.json --state-dir output/synthetic-check-01
```

このPCでは `output/cluster-deployment/START_CLUSTER_V5.cmd` と
`RESUME_12_MONTH_CHECK.cmd` を用意済み。前者は検証済みuv Python/固定版/同じキューで前景起動、
後者は同じ12件を再送重複なしで再開・監査する。新たな計算条件は新しいbatch manifestにする。
起動スクリプトのウィンドウを開いている間、`http://127.0.0.1:8868/` で操作する。
起動中に同じcontrollerを二重起動しない。自動常駐サービスは登録していない。
helperは修正済みのmain `tools/cluster/` を使う。旧固定版同梱のhelperを戻さない。

## 実行profile・共有枠・性能

`alns_no_gurobi_v1` はcanonical ALNS・1日診断に限定し、BESS/daily-return/rolling/formalは事前拒否。
native Env/Model禁止guardとgurobipy不在の検査を行った。既存のALNS exact repair付きとは別手法として扱う。
`existing_solver_v1` は既存挙動を保ち、通常ローカル・再最適化・cluster・license testを共有2枠へ通す。
プロセス終了後もWLS tokenのため330秒保持し、不明なremote実行は時間だけで解放しない。
外部アプリの利用分は `external_gurobi_slots` に明示する。現在のprivate設定は外部1枠を維持する。

PCの利用可能RAM、予約RAM、disk、CPU負荷/スレッド、AC条件、同じソース/profile/入力規模の実測時間を使う。
比較可能な履歴が揃うまではCPU型番やコア数から速度を推測しない。固定されたsolver threads/time limitを変えない。
Gurobi Threads=0は全CPUを予約し、空きCPU0とは扱わない。通常実行も親機の枠を共有する。
RAM要求は投入側が明示する。OSの強制メモリ上限ではないため、負荷の大きい実験は余裕を持って設定する。

UIを閉じても受理済みworkerは独立プロセスで継続し、親機再起動後に同じattemptを照合する。
停止要求は対象attemptに限定し、終了確認までは予約を保持。画面のstale表示は従機停止の証拠ではない。
成果物はattempt別に保存し、コピー/hash検証が完了してから公開する。

BFFの画面用ジョブJSONは同一IDへの更新をOSロックと単調増加する`state_version`で直列化し、固有名の一時ファイルから置換する。読込不能・形式不正・復旧保存失敗でも元JSONを削除せず、`/jobs/{job_id}`の`error`に原因種別を示す。分散キューの正本は従来どおりcluster SQLiteであり、画面用JSONを遠隔attemptの正本やローカルPID照会対象にしない。権限不足などで生成時刻を確認できないローカルPIDは「不明」のまま照合を要する。

---
## 実便版渋24の16台診断

新しいフロントで従来シナリオを表示するには、固定controllerの設定ファイルに既存のシナリオ保管先 `"scenarios": "C:/master-course/output/scenarios"` を指定します。これは管理者が管理するローカル設定であり、子機へシナリオ原本を直接共有しません。既存の画面でシナリオを選び、Prepareと実行を行えます。研究採用条件は従来どおり別に判定します。

実便版渋24の固定16件診断は、clean commitを全16台へ配置してから `tools/cluster/real_shibu24_batch.py --settings <controller-settings.json> --output <new-batch.json> --batch-id <new-id> --service-date 2025-05-12` で入力とbatchを作り、`tools/cluster/batch.py check <new-batch.json> --state-dir <new-state-dir>`、続いて同じ引数の `run` で実行します。作成コマンドは求解を始めません。IDと出力先を変えずに実行を再開すれば重複投入を避けられます。原本・パラメータ・研究上の限界は [実便版渋24の記録](notes/SHIBU24_REAL_CLUSTER_20260923.md) を参照してください。
