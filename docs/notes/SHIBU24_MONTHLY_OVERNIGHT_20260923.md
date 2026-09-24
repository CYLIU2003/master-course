# 渋24・2025年各月1週の翌朝SOC診断

2026-09-23時点の実験契約。これは診断入力と求解経路の実装記録であり、12週の結果や研究採用の宣言ではない。

## ODPT原本と最適化用DBの境界（2026-09-24更新）

時刻表はジョブごとに取り直さない。ODPT取得、取得原本の監査、最適化用DB生成は
研究者が明示的に実行する更新作業である。月別ジョブ・Prepare・求解からこの
更新作業を呼び出さない。現行の固定DBを使う限り、通常は下記の `verify` と
月別 `check` だけを行う。取得失敗、欠損、hash不一致時は停止し、古い原本へ
黙って戻したり、自動再取得したりしない。

新しい公開ダイヤを採用する時だけ、以下を**別の空の出力先**で手動実行する。
ODPT認証は既存の安全な設定から読み、コマンド引数・ログ・Gitへ鍵を載せない。

```powershell
$captureDir = 'C:\master-course\output\odpt_shibu24_NEW_VERSION'
$auditDir = 'C:\master-course\output\shibu24_source_audit_NEW_VERSION'
$dbDir = 'C:\master-course\data\optimization\shibu24_NEW_VERSION'
python scripts/audits/acquire_shibu24_odpt.py --output $captureDir
$captureManifest = Get-Content (Join-Path $captureDir 'shibu24_capture_manifest.json') -Raw | ConvertFrom-Json
python scripts/audits/audit_shibu24_source.py --capture-dir $captureDir --stop-source $captureManifest.stop_source_path --output $auditDir
python scripts/benchmarks/shibu24_optimization_store.py build --source $auditDir --destination $dbDir
python scripts/benchmarks/shibu24_optimization_store.py verify --destination $dbDir
```

監査は正規化路線カタログとの厳密なID照合を行う。公開側のパターンが変わって
照合できない場合、カタログも別途手動更新・監査し、同じ取得原本と結び直す。
成功しただけでは現行キャンペーンのDB指定は変更されない。新DBを研究比較へ
採用する場合は、DBパスとSHAを明示的に固定した新しい実験版を作り、全ケースを
新しいclean Git SHAからPrepareし直す。取得日・DB SHA・manifest SHA・便数・
路線集合を記録し、旧DB版の週や結果と混ぜない。取得した現行公開ダイヤを
2025年の実運行実績と呼ばない。

`output/shibu21_24_seasonal_20260911/odpt_shibu24_20260901/` の取得原本と
`shibu24_source_audit/` の加工済みJSON・manifestは保管・再構築用とする。
`python scripts/benchmarks/shibu24_optimization_store.py build` は原本SHAと
加工済み4表のSHA、operator、正の距離、便・停留所参照を検査し、
`data/optimization/shibu24_20260911/source.sqlite3` とmanifestを一度だけ作る。
既存DBは上書きせず、変更する場合は新しい出力先と新しい実験版を使う。
月別 `check` と `prepare` はDBを読取専用で開き、DB全体と各表のhash・件数を
照合する。ODPT原本や加工済みJSONは実行時に開かない。元の取得原本の
パス・SHAは出典メタデータとして保持し、欠損しても既に凍結済みのDBから
計算入力を再現できる。DBのSHAは各Preparedシナリオの出典に含める。
これはデータ経路の分離であり、ダイヤの2025年実績性、道路距離、正式fleet、
設備上限、研究採用を新たに証明するものではない。

## 比較対象と入力

- 2025年1～12月から各月1つ、月曜～日曜で平日ダイヤ5日・土休日ダイヤ2日となる7日間を、凍結済み `output/monthly_fair_weeks_20260914/week_selection.json` の規則で選ぶ。週は1/6、2/3、3/3、4/7、5/12、6/2、7/7、8/4、9/1、10/6、11/10、12/1開始。
- 渋24だけのODPT候補を使う。平日224便、土曜188便、日祝170便で、7日間の運行便は1,478便。operator IDと正の距離を照合する。距離は停留所座標の地理的代理値であり実道路距離ではない。2026年公開ダイヤを2025年の気象へ適用する仮想比較で、2025年実運行の復元ではない。
- PVの前日計画値は2024年のみで学習したclimatologyを、評価日の暦で生成する。8日目の翌朝についても独立して日付・96区間・hashを検証する。Solcast 2025実測は別原本として確認するが、今回のday-ahead求解を実時点のSolcast予報性能と呼ばない。
- 車両、充電器、BESS、電費、燃費、単価等は従来の渋21～23親シナリオから継承し、渋24の路線・便と日付別PVだけを差し替える。正式fleet承認、受電設備の実測hard limit、道路距離は未確認のため、出力は `DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS` とする。

## 電力とSOCの期間

運行需要は月曜0時から日曜24時までの7日間だけを含む。15分電力区間は672個に、翌月曜の最初の便の出発時刻までに完了できる区間だけを加える。05:47発なら翌朝05:45で終わる23区間を加え、計695区間とする。各営業日の帰庫後から翌朝最初の出庫前までに、その日運行したBEVはシナリオの運用SOC上限に達する。最終日も同じである。月曜朝の便そのものは8日目として求解へ追加しない。

延長区間には凍結済みの翌日PVと、シナリオで宣言した日次固定料金表の翌朝部分を使う。充電器同時使用、SOC遷移、BESS、買電、PV抑制、料金を同じ延長区間で評価する。日別費用台帳では最終夜間の充電と費用を最終営業日に配賦し、総額を期間費用と照合する。この配賦は会計表示であり、8日目の運行便を作ることや、車両別電源フローがソルバー原本であることを意味しない。

最終夜間を「含めない」設定もUIに保存できるが、この翌朝SOC目標との組合せは現時点では安全側で拒否する。SOC達成だけを求め、電力・料金のない無料充電を許す解釈にはしない。旧7日672区間の結果を今回の費用比較へ混ぜない。

## 実行・検証ゲート

`python tools/research/shibu24_monthly.py check` は凍結済み最適化DB、週選択、祝日、翌日ダイヤ、8日分PVを読み取り検査するだけで、シナリオ作成・求解はしない。`prepare --output <new-directory> --limit 1` でclean固定Git版から単週を複製し、既存の厳格Prepareへ通す。成功してから全12週を同一SHA・同一共通設定で新規Prepareする。出力ディレクトリはcampaignごとに新規とし、同じ週・原本・prepared IDを照合して再開する。Prepare成功、day-ahead可行、独立物理、台帳照合、rolling実行、研究採用、最適性は別々の状態として記録する。

Phase 3二段階のStage 1 gapはStage 1の目的に対する値であり、週間総費用の大域最適性を証明しない。最初の小規模native回帰では翌朝のSOC期限をStage 1/2双方へ課し、物理再計算と最終夜間充電費用の台帳一致を確認した。実規模1週・12週の通過、追加夜間のrolling実行、独立レビューはこれからである。

2026-09-23の実データ1月Prepareでは、表面上の`input_preparation_valid=true`にもかかわらず、内部の厳格接続監査が`NEXT_MORNING_TIMETABLE_MISSING`で未実施だった。Prepared原本は`trips`に全1,478便を保持する一方、設備側の翌朝検証が`timetable_rows`だけを参照していたことが原因である。設備側も`trips`を検査する修正と回帰テストを追加した。月別スクリプトは、厳格接続・折返し感度・車両適合監査が実際に通過した場合だけ`PREPARED`と記録する。修正前のPrepared IDとキャンペーンは新しい固定版に流用しない。

修正コードで初回1月原本を読取り専用で再監査した結果、厳格接続は`checked=true/infeasible=false`、回送接続と折返し感度はready、警告0件だった。緩和下界は19車両、登録60台である。この下界は実際に19台で運行できる証明ではない。修正版からの新規Prepare、実求解、翌朝までのrolling会計は引き続き別ゲートとする。

rollingの実測PV生成は従来7日分だけだったため、翌朝の実測日射行とraw原本SHAを契約へ固定し、追加区間のPVを実行入力へ含めた。rolling窓の終端も運行日数ではなく有料電力区間数から求める。これはコードと小規模回帰の通過であり、実規模の全時間窓・会計・物理の受入は別途確認する。

2026-09-23追記: 1月など翌朝05:45に終わる週は、60分rollingを173回行った後に45分の最終窓が必要となる。実行窓の長さを残り有料区間で切り、モデルの15分境界に一致する場合だけ最後の短縮を認めた。クラスタの予定窓数も同じ有料区間から計算する。実データ12週のPrepared入力が全件厳格監査を通過した後、`tools/research/shibu24_monthly.py batch`が原本SHAを再検査して12件の固定batchを作る。`tools/research/shibu24_monthly_campaign.py run --settings <fixed-controller-settings.json> --output <new-campaign-directory>`は既存Prepare・永続batch・成果物監査を順に呼び、失敗時は停止して記録を保持する。通常監視にAIを使わず、メールも自動送信しない。回収完了は研究採用や統合最適性を意味しない。
# 2026-09-24 新版統合の扱い

分散ジョブ管理の基準 `codex/worker-sort-passmark-20260923` (`5aa61f7a`) に本実験の翌朝SOC・月別自動実行を統合する。旧 `70f331b7` で完了した12週のPrepareは求解しておらず、新固定版のPrepared入力として扱わない。新SHAから12週を新規Prepareし、配布先のGit SHA・ソース・実行環境・データの証拠を全て一致させる。端末の配置失敗は監視状態に残し、投入を無効化する。これは実行版の変更であり、研究採用や最適性を意味しない。
