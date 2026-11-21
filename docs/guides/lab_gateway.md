# 研究室の計算PCを後輩のタスクに使う（ラボゲートウェイ）

2026-11-19。後輩が自分のPythonとGurobiのコードを、研究室の空いているPCへ自分で投入するための仕組みです。
修論用のクラスタ（8868/8891、`bff/services/cluster`）とは別のサービス・別のキューで動きます。台は修論で使えない台が中心で、
修論用の台は、修論の制御系が空きと報告しているときだけ借ります（下記「修論用の台を借りる」）。
コードは `tools/lab_gateway/`、テストは `tests/test_lab_gateway.py`（68件）。

## 仕組み

```text
後輩のPC（lab_client.py）  --HTTP + 個人トークン-->  親機のゲートウェイ  --SSH/scp-->  空いている計算PC（run_job.py）
```

- 後輩はフォルダを1つ送ります（zip、100 MiB以下）。実行するのは `python <entry> <args>` だけで、任意のシェルは使えません。
- 親機が、プールの中の空いていて条件を満たす台を選び、台に置いて起動し、終わったら結果を回収します。
- 1台につき同時に1件。後輩1人あたり同時に動くのは2件、未完了は20件まで。
- 台の判定：PythonとGurobi環境がある／要求RAMが台の上限（搭載−8 GiB）以内／空きRAMが要求＋1.5 GiB以上／CPU負荷85%以下／ディスク空き5 GiB以上。
  どの台でも上限を超える要求は `REJECTED`（理由つき）、台がつながらないだけなら待ちます。
- 各台のGurobiは、その台のユーザーに入っている個人のライセンスをそのまま使います（台帳の `gurobi_license_file` は使いません。
  desktop-0srs8pr と powersystem では旧WLSファイルを指していて期限切れのため）。
- 実行は台の上で切り離して動くので、ゲートウェイを再起動しても続き、起動後に状態を拾い直します。確認できなくなった件は `LOST`
  になり、自動では再実行しません。

## 使える台（プール）

`output/lab-gateway/config.json`（Git管理外）の `machines` に台帳のIDで並べます。**修論用の台は入れません。**
2026-11-21、運用者の指示で、修論モデルで使えない台（搭載RAMが修論のGurobi受け入れ条件24GB未満）8台にしました。

| 台 | RAM | 備考 |
|---|---|---|
| cyliu-thinkbook | 23.8 GiB | 2026-11-19 実機で極小LPが最適。ライセンス 2881171 |
| powersystem | 15.9 GiB | 同上。ライセンス 2873520 |
| desktop-0srs8pr | 7.9 GiB | 同上。ライセンス 2873732。上限約3.9 GiBで小さいタスクのみ |
| cyliu-dell-7260 | 15.9 GiB | 11/21追加。ライセンス 2873518 |
| pslab-e490 | 7.8 GiB | 11/21追加。ライセンス 2873531。上限約3.9 GiB |
| laptopintel8 | 15.8 GiB | 11/21追加。ライセンス 2873729 |
| laptop-fem8jhv2 | 15.9 GiB | 11/21追加。ライセンス 2873521 |
| laptop-d0stmfn4 | 15.9 GiB | 11/21追加。ライセンス 2873522 |

11/21追加の5台は、SSH・`C:/mc-worker/venv`・空きRAMを読取で確認しただけで、ゲートウェイ経由の実行はまだ試していません。

## 修論用の台を借りる（2026-11-21）

`config.json` の `"thesis_overflow": {"controller": "http://127.0.0.1:8891", "max_minutes": 360, "keep_idle": 2}` で有効になります（`tools/lab_gateway/overflow.py`）。

- 借りるのは、プールの台がすべて埋まっているか条件を満たさないときだけ。
- 対象は、修論の制御系（8891）が `READY`・`active`・実行中なし・予約なしと報告している台だけ。修論の待ちジョブがあるときは、
  空いている台のうち性能の高い順に `keep_idle`（2台）を修論用に残し、残りを性能の低い順に貸します。
- 借りる前に、その台を修論の制御系の「新規割当停止（draining）」にし、直後に読み直して修論のジョブが入っていたら取りやめて元に戻します。
  後輩のタスクが終わると「active」に戻します。誰かが途中で無効化した台は戻しません。
- 時間上限が `max_minutes`（360分）を超えるタスクは借りません（修論の台を長く止めないため）。要求RAMがプールのどの台の上限も超えるが
  24 GiB以下なら、`REJECTED` にせず修論用の台が空くのを待ちます。
- 修論の待ちジョブ数は `"queue_db"`（修論キューの `cluster.sqlite3`、読み取り専用）から数えます。未指定なら制御系の `/api/cluster/jobs` を使いますが、
  全ジョブを返すため数十MBになります。制御系（8891）のHTTPが止まっているとき（`batch.py run` だけで回しているとき）は借りません。
- 借りている台は `overflow_claims.json` に記録し、ゲートウェイ再起動時に実行中なら続きを追い、終わっていれば返します。
- 借りている間に修論の計算が来ても、後輩のタスクを止めて明け渡すことはしません（その台は修論の新規割当から外れたまま）。
- `lab_client.py pool` の一覧に、借りている台が `"borrowed": true` で出ます。

台を足す条件：親機から `ssh` でつながり、`C:/mc-worker/venv` のPythonでgurobipyが動き、その台のユーザーの環境でGurobiの極小LPが解けること。
使える主なパッケージは gurobipy、numpy、pandas、scipy、pydantic です（台の環境のまま。追加導入はしません）。

## 運用者（劉）の手順

1. **起動**：`output\lab-gateway\START_LAB_GATEWAY.cmd [ホスト] [ポート]`。既定は `127.0.0.1:8899`（このPCだけ）。後輩へ配る接続情報は
   Tailscale（100.74.254.53）と学内LAN（133.78.186.228）の両方を書いてあるので、`START_LAB_GATEWAY.cmd 0.0.0.0` で起動します。
   後輩4人分（junior1〜junior4）のトークンと個人フォルダは `output\lab-gateway\handouts\juniorN\`（`指示書.md` に接続情報つき、`lab_client.py`）。
   フォルダごと本人にだけ渡します。名前を変えたいときは `token-revoke` で失効して `token-add` で発行し直します。
   後輩から届かせるには、このPCのLANまたはTailscaleのアドレスを第1引数に渡します。
2. **届く経路（あなたが行う設定変更）**：ポートを開けるWindowsファイアウォールの許可と、後輩のPCから親機へ届くネットワーク。
   通信はHTTPのため、LANの外へは出さず、できればTailscale（暗号化）経由にします。例（管理者PowerShell、サブネットは実環境に合わせる）：
   `New-NetFirewallRule -DisplayName lab-gateway -Direction Inbound -Protocol TCP -LocalPort 8899 -RemoteAddress <後輩のPCのサブネット> -Action Allow`
3. **トークンの発行**（人ごとに別々に渡す）：`output\lab-gateway\LAB_ADMIN.cmd token-add <名前>` — トークンは1回だけ表示され、親機にはSHA-256だけ残ります。
   本人にだけ個別に渡します（パスワードマネージャーなど）。無効化は `token-revoke <名前>`、一覧は `token-list`。
4. **監視**：`output\lab-gateway\audit.log`（時刻・名前・操作・応答コード。トークンは書かれません）、`jobs.sqlite3`（キュー）、`results\`（結果）。

## 後輩の使い方（AI向けの指示書は [junior_ai_instructions.md](junior_ai_instructions.md)）

`tools/lab_gateway/lab_client.py` を自分のPCへコピーし、環境変数 `LAB_GATEWAY_URL`・`LAB_GATEWAY_TOKEN` を設定します。

```text
python lab_client.py submit ./my_project --entry main.py --ram 4 --time 60 --threads 2 --name my-run --key my-run-1
python lab_client.py wait JOB_ID          # 終わるまで待つ（COMPLETEDなら終了コード0）
python lab_client.py fetch JOB_ID --out ./results
python lab_client.py list | status JOB_ID | cancel JOB_ID | pool
```

プログラムは、結果を環境変数 `MC_LAB_OUTPUT_DIR` のフォルダへ書きます。そのフォルダと標準出力・標準エラーが `result.zip` で返ります。

## 状態

`QUEUED`（待ち）→`STAGING`（台へ配置中）→`RUNNING`→`COLLECTING`→`COMPLETED`／`FAILED`（終了コードが0以外、または台で起動しなかった）／
`TIMEOUT`（時間上限で停止）／`CANCELLED`／`LOST`（確認できなくなった。台でまだ動いている可能性がある）／`REJECTED`（要求がどの台の上限も超える）。

## 検証したこと／していないこと

- 確認済み：単体・API・ディスパッチャーのテスト56件。実機（cyliu-thinkbook、powersystem）で、成功（Gurobiで最適解13.0、結果と標準出力の回収）、
  失敗（終了コード7の報告）、実行中の取り消し（プロセス停止とフォルダ削除）。実機で見つかった不具合（SSH切断で子プロセスが消える、
  開始前の取り消しが止まる、開始しない実行が`RUNNING`のまま残る）は修正し、テストを足した。
- **していない・できていないこと**：後輩のPCからの接続（経路は運用者の設定が要る）。修論の計算が来たときの割込み（借りている台を明け渡す処理）は未実装。
  修論用の台を借りる処理は偽の制御系でテストしたのみで、実際に借りた実績はまだない。台の再起動・スリープ中の実行は `LOST` になる。
  トークンの総当たり対策（回数制限）とTLSは未実装。台のログインユーザー権限でコードが動く点は運用者が了承した上での仕様。
