# 1月の原計算を再求解せず週次比較へ復旧

2026-09-27。開発元2bda7fdc、計算固定版f524eca2552a4386bd033a15bbe046c14dc09281。

## 根拠と結果

1月のworker c094649e-5a99-5ba6-b043-f2b832b76066は、図表生成で異なる日の05:45のCO2係数が衝突してFAILED。
図表修正後のコピーを再検査すると、必要717ファイルは存在し、content/workbookエラー0、
最後のrun_manifest.files更新のみ未完了だった。原worker・queue・ZIPは変更せず、別コピーの一覧だけ更新。
717件の成果物検査、1,704便充足、697区間の実行会計、日別合計、電力収支を確認し、週次CSV・図を出力した。
これは記録済み物理判定と原本の再照合であり、新しい物理モデル求解ではない。

総費用4,860,462.656698648円。車両日費4,100,000円、買電費197,891.04475274202円、
燃料費36,317.878573008806円、契約超過のモデル費522,329.4544896007円、CO2費3,924.2788832960864円。
1,704便、営業距離13,925.428829km、車両日205。最終翌朝の充電・受電・費用を含む。
設備費未計上・受電設備の仮定・BESS在庫取崩し・電費一定・統合最適性未証明という条件は変更しない。

月別比較は1〜10月の10/12週に増加。11/12月は同じ試行が継続中。
9件の通常完了と1件のREPORTING_RECOVEREDを区別。原キャンペーンのFAILEDを成功へ変更しない。

## 実装

- recover_weekly_reporting.py：原ZIP SHA、worker/bundle/Prepared/source/要求の対応、図以外の不変性を検査。
- 別コピーのrun_manifest.filesだけ修復し、既存artifact auditを実行。元の研究判定を保持。
- weekly_collection.py：既存の週次検算・CSV/図出力を共有関数へ抽出。式・条件は変更なし。
- monthly_campaign_report.py：明示した--reporting-recoveryだけ別証拠区分で比較へ追加。
  配布コピーを原ZIPと直接比較し、過去の絶対output_run参照を辿らない。
- 自動集計だけを旧監視から置き換え、同じmonthly_reportへ配信。controller/solverの再起動・新規投入なし。

## 検証・独立レビュー

関連80件通過後、追加2件を含む変更対象28件通過（重複を足さない、合計82ケース）。
最初の負例テストは原データと同じ{}を書いていたため失敗し、実際に異なる値を注入するよう修正した。
1月の実データと10週比較を実行し、PNGの日本語・軸・期間・単位を表示確認した。

Claude Sonnet 5で読取専用レビューを実施。指摘を以下のとおり判断した。

- solver_usageを許可リストへ追加する案：不採用。原ZIPに存在し同一hashであることが必要であり、追加証拠は拒否する仕様。
  原本のsolver_usageが通るテスト、追加非figureを拒否するテストで確認。
- manifestの判定が書換わる懸念：ファイル一覧以外のJSON等値検査と、acceptance改変拒否テストを追加。
- prefix懸念：対象名は必ず/rolling_hourly_chain/executed_day_accounting.jsonで終わるものから導出し、該当1件を要求している。
- output_run参照：依存を除去し、配布済みrunを直接原ZIPに照合する実装へ改善。

研究採用・統合最適性の独立承認ではない。第三者による物理再計算と残り2週の完走は未確認。
証拠はoutput/january_reporting_recovery_20260927、
output/executed_soc_20260926/report_recovery/january-weekly-v2、monthly_report内のimmutable revision。
元のfailed ZIP、最初の図修復コピー、v1検証出力も保持。
