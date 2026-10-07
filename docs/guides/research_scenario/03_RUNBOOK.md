# 3. フロントとCLIからの実行・再開

## 作業を選ぶ

既存12週は最新比較revisionにそろっている。依頼が集計・資料作成なら[結果ガイド](04_RESULTS.md)へ進み、新規求解しない。再計算が必要な場合は、同じ試行の再開か、新条件の新実験かを最初に分ける。

通常の研究操作にAIを組み込まない。操作ツール、queue、worker、回収・検算を既存の経路で動かす。ここに載るコマンドは使用版のソースで引数を確認した。実行時も必要に応じて同じPythonの `--help` を見る。

## フロントで確認・保存する

このPCに配置された操作画面のURLはsettingsのportで確認する。今回の記録は `http://127.0.0.1:8891/`。2026-10-06の文書確認時にはAPI応答未確認であり、ここで画面の稼働・最新UIの配置を保証していない。

ソース上の画面構成と操作順は次のとおり。

1. 「シナリオを切り替える」で「仮・正式用」を選ぶ。分類は「渋21〜23」。名前だけでなく親IDと実験を確認する。
2. 「設定確認・保存」で営業所、選択路線・パターン、期間、車両・設備、費用、SOC方策を確認する。未保存変更があるまま実行しない。
3. 「期間別計画」に開始日・日数・名称を登録する。各月を別の親シナリオとして増やさない。登録と保存は求解開始ではない。
4. 「実行開始・進捗」で処理、Prepared、計画方式、診断／正式区分、単機／分散の対象を確認する。入力条件変更後は正規Prepareを作り直す。
5. 「分散計算」でcontroller、scenario、job/attempt、担当PC、工程、待機理由、RAM、保存済み時間・検算・集計を確認する。
6. 「グラフ・費用明細」「月別の結果」で原結果と集計を確認する。

現在の週次条件付き実験では複数日研究ゲートを通過済みとはしていない。`MULTIDAY_RESEARCH_BLOCKED` を消して正式研究実行にする方法を採らない。`mode_milp_only` はPhase 3二段階である。解法名だけで週統合最適化と表示しない。

期間登録は1〜366日を扱うが、`weekly_campaign.py` は7日間のdriverである。期間リストに1日と7日が混在すると `scenario_periods.py export` は拒否する。任意の日数を7日へ丸めず、そのrunに対応する期間を明示して実行する。期間画面の機能だけで、連続数週間の求解や12件の一括投入が保証されるわけではない。

別controllerの一覧を監視している時は閲覧専用。表示しているAPIのportと、操作対象のqueueを照合する。別queueのjobを現在のcontrollerのものとして取り消さない。

## CLIの準備

PowerShellで、実在するoperationを指定する。下記は今回の保存済み実験に対する変数宣言で、計算を開始しない。

```powershell
$repo = 'C:/master-course'
$experiment = "$repo/output/executed_soc_20260926"
$operation = "$experiment/operation.remaining.local.json"
$definition = Get-Content -LiteralPath $operation -Raw -Encoding UTF8 | ConvertFrom-Json
$settingsPath = [string]$definition.settings
if (-not [IO.Path]::IsPathRooted($settingsPath)) {
    $settingsPath = Join-Path (Split-Path -Parent $operation) $settingsPath
}
$settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$solverPython = [string]$settings.python
```

2月を操作する時は `$operation = "$experiment/operation.local.json"` として同じ読み込みを行う。2月とほかの11週は内部campaignが別で、親シナリオは同じ。別のPythonへ勝手に切り替えない。

## 既存試行の操作

```powershell
# 保存済み状況と、接続できれば同じcontrollerの状態を確認
& "$repo/tools/research/weekly_operations.ps1" -Operation $operation -Action status

# 固定SHA、入力・設定・環境の事前検査。新規求解・license trialなし
& "$repo/tools/research/weekly_operations.ps1" -Operation $operation -Action check
```

`status` は読み取りを基に、operations配下の観測記録・必要な未送信通知ファイルを更新し得る。原workerの計画・会計を変更せず、新規jobは作らない。完全なファイル無変更が必要ならJSONを直接読む。

以下は開始・続行が依頼されている時だけ実行する。

**controller起動は読み取り専用ではない。** BFF起動時に既存schedulerが動き、既存QUEUEDの割当が再開し得る。自動復旧supervisorを別途有効にする操作とは別で、どちらも実行へ影響し得る。状況確認・回収だけの依頼では、APIが不通でもcontrollerを自動起動しない。対象queueの継続も依頼範囲に含まれる時だけ起動する。

```powershell
# 同じ管理サーバーとschedulerを起動する。既存QUEUEDの割当も再開し得る
& "$repo/tools/research/weekly_operations.ps1" -Operation $operation -Action controller

# 同じbindingで未投入を続行・既存試行を追跡する
& "$repo/tools/research/weekly_operations.ps1" -Operation $operation -Action run
```

controller窓は運用中に残す。再開は同じcampaign、weeks、workers、親、SHAを保持する。`ALREADY_ACTIVE` は既存所有者がいるという意味で、新規投入成功ではない。失敗した求解を自動的に別attemptへ再実行するコマンドではない。

回収・集計を依頼された時の入口：

```powershell
# 同じ試行の回収・検算。新規投入なし
& "$repo/tools/research/weekly_operations.ps1" -Operation $operation -Action collect

# 状況記録と必要な代理回収を30秒ごとに実施。AI呼出しなし
& "$repo/tools/research/weekly_operations.ps1" -Operation $operation -Action watch
```

watchのCtrl+Cは監視だけを止める。受理済み遠隔計算を停止しない。通常の操作をAI heartbeat、毎時のモデル呼出し、無限再投入へ置き換えない。

| 終了コード | 読み方 |
|---|---|
| 0 | 操作が成功した。全週完了の意味ではない |
| 3 | 未完了、回収不足、通信状態不明等 |
| 2 | 設定・操作エラー |
| 130 | 利用者が監視を中断 |

`check` と `run` は下位プロセスの終了コードを継承する。件数・期待区間数・検算状態は別に確認する。

## 新実験のoperationを用意する

既存operationを編集して旧実験を別条件に変えない。新しい出力ルートと確定済みcontroller設定を用意し、次の形で宣言する。

```json
{
  "settings": "C:/.../new-controller-settings.json",
  "campaign": "C:/.../new-experiment/campaign",
  "git_sha": "<実行を凍結したclean commitの40桁SHA>",
  "parent": "<選んだ親シナリオID>",
  "weeks": ["2025-01-06", "2025-02-03"],
  "workers": ["auto"]
}
```

これは書式例であり、そのまま実行できる設定ではない。12週を依頼された場合は[12週一覧](01_CONTEXT.md)を宣言する。weeksの一部だけを使う時は診断・選択条件を明示する。

operationのsettings/campaign相対パスは、そのJSONの置き場所を基準に解決される。controller設定のpython/release/config/queue/outputs/scenarios/frontendは絶対パスを使う。settingsにはgit_sha、source_digest、runtime_versions等の対応も必要で、releaseのパスだけを新しいコードへ差し替えて済ませない。

controller設定をゼロから推測して作らない。既存の[配布候補確認記録](../../notes/NEXT_WEEKLY_RELEASE_20260927.md)、`tools/cluster/release.py`、`tools/cluster/serve_controller.py` の契約を確認する。ZIPが展開できたことと、remote環境・ライセンス・週次求解が通ることは別である。

## 期間別計画をCLIで読む

対象storeをsettingsから設定してから実行する。親機の別storeを既定値で読まない。

```powershell
$env:SCENARIO_STORE_PATH = [string]$settings.scenarios
& $solverPython -X utf8 "$repo/tools/research/scenario_periods.py" show `
    --scenario '771d115b-75b0-49f7-a7f0-25f259a2cd21'

# 全登録期間が7日間の場合だけexport可能。新規ファイルへ出す
& $solverPython -X utf8 "$repo/tools/research/scenario_periods.py" export `
    --scenario '771d115b-75b0-49f7-a7f0-25f259a2cd21' `
    --output '<まだ存在しない期間plan JSONの絶対パス>'
```

exportした `scenario_week_plan_v1` はdriverの `--period-plan` で使用できる。しかし通常はoperationから操作する。driver直起動を行う必要がある場合は、settingsによるstore/queue/出力の構成を正規の `serve_controller.configure()` 相当で適用した固定release内で行う。開発rootから単にdriverへ `--settings` を渡しても、全環境が正しく設定される保証はない。`weekly_operator.resume_command()` がその構成と起動を行う実装入口である。

## 新しい操作メニューを作る

既存の確定済みoperationから未使用のフォルダへ入口を生成できる。生成はjob投入ではない。

```powershell
& $solverPython -X utf8 "$repo/tools/research/install_operator_kit.py" `
    --operation '<確定済み新operationの絶対パス>' `
    --output '<新しい操作フォルダの絶対パス>'
```

このPCに設置済みのメニューは `C:/master-course/output/operations/weekly_20260927/00_MENU.cmd`。メニューの対象が古い実験か、新しい実験かを毎回確認する。

## 配置・資源・安全な再開

Gurobiは32GB以上の許可済み端末のみ。32GB機は約16GiB、64GB機は約32GiBを目安とし、空きRAM、OS・サービス予約、Windowsコミット、モデル要求を既存schedulerで判定する。16GB機へ同じGurobi週次モデルを投げない。標準機は対応する軽い準備・検算・集計へ利用する。

並列度は端末数ではなく、正当に利用できるライセンスpoolとbrokerの予約で決まる。Envの解放待ち・通信不明の枠を保留する。ALNSという名前だけでGurobi不要と判断しない。軽量監視で `is_gurobi_available()` やlicense trialを全PCへ走らせない。

親機も余力を残して計算へ参加できる。親機を管理専用へ固定しない。今回の18台台帳と、投入適格PCの数は別。最新のRAM・環境・ライセンスを確認し、過去の5台や2枠を永久定数にしない。

親機復帰時は同じqueue・attemptの照合を先に行う。管理サーバーの自動復旧を有効化すると、既存QUEUEDの割当も再開する。回収専用モードと誤認しない。詳細は[週次運用ガイド](../weekly_operations.md)にある。今回の文書作成では再起動や有効化を行わない。
