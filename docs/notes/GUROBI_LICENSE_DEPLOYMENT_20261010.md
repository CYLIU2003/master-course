# 2026-10-10 Gurobiライセンス導入の作業メモ

## 2026-11-03〜04 新規3台

ユーザーの明示指示で、Free Academic Named-User（Gurobi 13）を各1件発行・導入した。
発行はagent-browserの別セッション `mr7177o-gurobi`（ログイン済みポータル）、配置は既存 `deploy_named.py` の
`INSTALL_SCRIPT` をSSHで使った。キーコードはメモリ上でSSH stdinへ渡し、記録・Gitには残していない。

| 子機ID | 実機名 | ユーザー | ライセンスID | 期限 |
|---|---|---|---|---|
| desktop-mr7177o | DESKTOP-MR7177O | pslab | 2880832 | 2027-11-03 |
| pslab-mouse | PSLAB_MOUSE | pslab | 2881169 | 2027-11-04 |
| cyliu-thinkbook | CYLIU_THINKBOOK | a0411 | 2881171 | 2027-11-04 |

3台とも `%USERPROFILE%\gurobi.lic`（保護ACL）とUser環境変数 `GRB_LICENSE_FILE` を設定。
CYLIU_THINKBOOKの既存 `gurobi.lic` は `.before-20261010-*.bak` に退避した。
PSLAB_MOUSE・CYLIU_THINKBOOKでは venv の gurobipy 13.0.1 で Threads=1 の極小LPがOPTIMALになることを確認した（研究計算ではない）。
ポータルは2回目の発行からEULA同意フォームを表示した。ページ読込直後の「今すぐ発行!」クリックは無反応のことがあり、
一覧で新規IDが無いことを確認してから再操作した。重複発行はない。研究計算への割当許可は意味しない。

## 2026-10-12 追加導入

初回にオフラインだった2台が起動した後、既存SSH鍵で接続し、Free Academic
Named-User（Gurobi 13）を各1件発行・導入した。ユーザーはGurobi EULAへの同意と
2台分の発行を明示確認した。発行コードは一時的にメモリ上で導入処理へ渡し、
メモ・JSON・Gitには保存していない。

| 子機ID | 実機名 | Tailscale IP | Windowsユーザー | 新規ライセンスID | 期限 |
|---|---|---|---|---|---|
| laptopintel8 | LAPTOPINTEL8 | 100.72.59.121 | a0411 | 2873729 | 2027-10-12 |
| desktop-0srs8pr | DESKTOP-0SRS8PR | 100.90.78.55 | a0411 | 2873732 | 2027-10-12 |

両端末とも `%USERPROFILE%\gurobi.lic` と保護ACL、端末名・ユーザー、gurobipy
13.0.1、User環境変数 `GRB_LICENSE_FILE` を照合した。旧WLS `2846699` とMachine
環境変数は保持した。最終照合は17/17台で成功し、controller設定SHA256は前後で一致。
2台のRAMは15.8GBと7.9GBで、搭載32GBのworker admission条件を満たさないため、
この導入は研究計算への割当許可を意味しない。求解や新規研究実行は行っていない。

## 結果

フロント8868の子機17台すべてにFree Academic Named-User（Gurobi 13）を新規発行・
導入した。初回の2026-10-10は接続できた15台を23:20 JSTに照合し、残る2台は
2026-10-12の起動後に追加導入した。最終確認では17/17台のファイル・端末・ユーザー・
参照先を照合済み。
親機NOVACOR-PCは既存Named-User `2846706` を保持した。

ユーザー指定は「Named-Userでよい」「全部私の端末」。
ポータルの発行はagent-browserの専用セッション、配置はSSHで行った。
個人用Named-Userの導入と、常駐分散workerのライセンス方式は分けて扱った。

## 導入一覧

先行15台のファイルは `VERSION=13`、`EXPIRATION=2027-10-10`。
ポータルのGMT+9表示は2027-10-11であり、この記録はファイルのEXPIRATIONに従う。
追加2台のファイルは `VERSION=13`、`EXPIRATION=2027-10-12`。

| 子機ID | 実機名 | Tailscale IP | Windowsユーザー | 新規ライセンスID |
|---|---|---|---|---|
| desktop-6ae0mir | DESKTOP-6AE0MIR | 100.122.202.117 | a0411 | 2873516 |
| cyliu-dell-7260 | CYLIU-DELL_7260 | 100.68.16.121 | a0411 | 2873518 |
| desktop-1800n4s | DESKTOP-1800N4S | 100.64.231.27 | pslab | 2873514 |
| pslab-e490 | PSLAB_E490 | 100.84.112.87 | pslab | 2873531 |
| powersystem | POWERSYSTEM | 100.88.215.76 | pslab | 2873520 |
| laptop-fem8jhv2 | LAPTOP-FEM8JHV2 | 100.82.33.8 | pslab | 2873521 |
| laptop-d0stmfn4 | LAPTOP-D0STMFN4 | 100.110.178.15 | pslab | 2873522 |
| matlab-desktop | MATLAB_DESKTOP | 100.80.250.27 | powersystem_desktop | 2873523 |
| laptop-a709una0 | LAPTOP-A709UNA0 | 100.93.186.52 | pslab | 2873524 |
| desktop-5b6f6bp | DESKTOP-5B6F6BP | 100.121.87.16 | pslab | 2873525 |
| powersystem-1 | POWERSYSTEM | 100.107.38.117 | pslab | 2873526 |
| desktop-6s6ua9u | DESKTOP-6S6UA9U | 100.112.33.11 | tate8 | 2873527 |
| desktop-3pru7qp | DESKTOP-3PRU7QP | 100.94.194.33 | pslab | 2873528 |
| laptop-bolc6vit | LAPTOP-BOLC6VIT | 100.65.118.103 | pslab | 2873529 |
| laptop-8js4dqcd | LAPTOP-8JS4DQCD | 100.87.44.64 | pslab | 2873530 |
| laptopintel8 | LAPTOPINTEL8 | 100.72.59.121 | a0411 | 2873729 |
| desktop-0srs8pr | DESKTOP-0SRS8PR | 100.90.78.55 | a0411 | 2873732 |

同じ実機名POWERSYSTEMの2台は子機ID・IP・既存SSHホスト鍵で区別した。
親機の既存ファイルは `TYPE=ACADEMIC`、`VERSION=13`、
`EXPIRATION=2027-07-20`（ポータル表示2027-07-21）を読取確認した。

## 保存先と参照先

- 新規ライセンスは各ユーザーの `%USERPROFILE%\gurobi.lic` に配置。
  原本は `%USERPROFILE%\.master-course\named-user-20261010\gurobi.lic` に保持。
- 個人用User環境変数 `GRB_LICENSE_FILE` を新しい配置先へ設定。
  Machine環境変数は保持し、変更前のUser/Machine値を同ディレクトリの
  `user-environment-before.json` に保存した。
- MATLAB_DESKTOPの旧default WLS `2785206` は `.before-20261010-*.bak` に退避し、
  旧LICENSEIDの保存を照合した。workerが明示指定する `.master-course\gurobi.lic` は保持。
- ライセンスとバックアップは所有者・SYSTEM・Administratorsのみ許可するACLで保護。
  発行コードは導入時に一時使用し、作業メモ・証跡JSON・Gitには記載していない。
  ライセンスKEY・WLSSECRETなどの値も作業メモや証跡ファイルには保存していない。

既に開いているPowerShell・IDEなどのProcess環境変数には古い値が残る場合がある。
新しい個人用プロセスの起動前に確実に指定する場合は、次を設定する。
これは参照先の指定のみで、ソルバーを起動しない。

```powershell
$env:GRB_LICENSE_FILE = Join-Path $env:USERPROFILE 'gurobi.lic'
```

## 初回導入時に接続できなかった理由

23:15 JSTのTailscale・TCP確認では、以下の2台はTailscaleオフライン、ping不応答、
TCP22/5985/3389へ到達不可だった。電源断・スリープ・ネットワーク断のどれかは未確定。
ライセンス発行上限や認証失敗で止まったわけではない。

| 子機 | IP | Tailscale最終接続（JST） |
|---|---|---|
| LaptopIntel8 | 100.72.59.121 | 2026-10-06 12:44 |
| DESKTOP-0SRS8PR | 100.90.78.55 | 2026-10-08 15:50 |

PSLAB_E490は初回、Tailscale pingには応答したがSSHがタイムアウトした。
再検査でTCP22が開き、23:16 JSTに同じユーザー・既存鍵でSSH接続できたため追加導入した。
復帰原因は未確定であり、SSHサービス・ファイアウォールを修正したとは記録しない。
2026-10-12にユーザーが両端末を起動した後、Tailscaleオンライン状態、実機名・ユーザー、
既存SSH鍵による接続を確認し、上記のライセンスを各端末へ導入した。

## 研究計算への影響と検証範囲

公式の[Academic発行案内](https://support.gurobi.com/hc/en-us/articles/360040541251-How-do-I-obtain-a-free-academic-license)は、
追加コンピューター向けの新規発行を案内している。
[Gurobi EULA](https://www.gurobi.com/EULA)の1.bと3.aにはNamed Userの共有処理・
バッチ処理・バックグラウンドサービス利用の制限があるため、今回の個人用導入を
常駐分散workerへの切替や同時実行数の増加とは扱っていない。

稼働workerは設定の `gurobi_license_file` を `--license-file` で渡し、runnerが
Process環境変数へ明示指定する。個人用User環境変数より、この指定が優先する。
既存WLSファイル、workerのGurobi有効フラグ、共有2枠、
[搭載32GB以上の条件](GUROBI_ADMISSION_POLICY_20260925.md)は継続した。
少ないRAMの端末への導入は、その端末の研究求解への割当許可を意味しない。

23:17 JSTの読取確認では8868は共有2枠・外部予約2、8891は共有2枠・外部予約0。
8891の `efd44db0-454f-5bca-b0ca-5d4dbac80fa3` はLAPTOP-A709UNA0でRUNNINGだった。
controllerのPID 63264/82212は継続し、再起動・再投入・ジョブ停止は行っていない。
既存WLS `2846699` のポータル表示は2セッション・2026-10-19まで。
今回のNamed-User発行では、その期間・セッション数は延長されない。

確認済み：grbgetkeyによる17台の取得成功、ID/HOSTNAME/USERNAMEとHOSTID/KEYの存在、
原本・配置先SHA256、ACL、User側参照先、全17台のgurobipyパッケージmetadata 13.0.1、
保持した旧ライセンスmetadata、個人用設定の変更前後のcontroller設定SHA256一致。
必要なgrbgetkeyは親機の既設13.0.1からコピーしSHA256を照合した。
ヘルパーのPythonコンパイルとPowerShell構文も確認した。

Env/Model/optimizeによる求解試験・新規研究実行は行っていない。
数理モデル・Prepared入力・時刻表・研究受理条件・保存済み結果は変更していない。
正式研究受理や独立レビューの完了を表す記録ではない。
残作業は常駐分散計算に適したライセンス方式の確認（本件の個人用Named-User導入とは別）。

## ローカル証跡

資格情報を除いた記録はGit管理対象外の `output/gurobi_licenses_20261010/` に保存した。

- [初回一覧](../../output/gurobi_licenses_20261010/inventory_initial.json)と
  [E490復帰後の一覧](../../output/gurobi_licenses_20261010/inventory.json)
- [発行・導入記録](../../output/gurobi_licenses_20261010/named_deployment.json)
- [17台の最終照合](../../output/gurobi_licenses_20261010/verification.json)
- [接続再確認](../../output/gurobi_licenses_20261010/connectivity.json)
- [controller・親機の読取確認](../../output/gurobi_licenses_20261010/controllers_after.json)

編集中のPowerPointと未追跡の研究方向資料は保持し、コミットは行っていない。
