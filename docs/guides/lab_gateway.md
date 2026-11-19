# 研究室の計算PCを後輩のタスクに使う（ラボゲートウェイ）

2026-11-19。後輩が自分のPythonとGurobiのコードを、研究室の空いているPCへ自分で投入するための仕組みです。
修論用のクラスタ（8868/8891、`bff/services/cluster`）とは別のサービス・別のキュー・別の台で動き、修論の計算には触れません。
コードは `tools/lab_gateway/`、テストは `tests/test_lab_gateway.py`（56件）。

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

`output/lab-gateway/config.json`（Git管理外）に台帳のIDで並べます。現在は修論用でない3台です。**修論用の台は入れません。**

| 台 | RAM | 確認（2026-11-19、実機で極小LPが最適） |
|---|---|---|
| cyliu-thinkbook | 23.8 GiB | Gurobi 13.0.1、ライセンス 2881171（2027-11-04まで） |
| powersystem | 15.9 GiB | Gurobi 13.0.1、ライセンス 2873520（2027-10-10まで） |
| desktop-0srs8pr | 7.9 GiB（空き0.6 GiB） | Gurobi 13.0.1、ライセンス 2873732（2027-10-12まで）。上限は約3.9 GiBで小さいタスクのみ |

台を足す条件：親機から `ssh` でつながり、`C:/mc-worker/venv` のPythonでgurobipyが動き、その台のユーザーの環境でGurobiの極小LPが解けること。
使える主なパッケージは gurobipy、numpy、pandas、scipy、pydantic です（台の環境のまま。追加導入はしません）。

## 運用者（劉）の手順

1. **起動**：`output\lab-gateway\START_LAB_GATEWAY.cmd [ホスト] [ポート]`。既定は `127.0.0.1:8899`（このPCだけ）。
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
- **していない・できていないこと**：後輩のPCからの接続（経路は運用者の設定が要る）。修論用の台へのあふれ出しと、修論の計算が来たときの割込み
  （プールは修論用でない台に限定。修論用の制御系との連携が要るため未実装）。台の再起動・スリープ中の実行は `LOST` になる。
  トークンの総当たり対策（回数制限）とTLSは未実装。台のログインユーザー権限でコードが動く点は運用者が了承した上での仕様。
