# 2026-09-23 残件の実装と研究採用境界

追記: `run_exact_seasonal_campaign.py --carry-bess`と専用の`tools/research/run_bess_continuous_diagnostic.py`で、隣接する2025-01-20/01-27の2週を新規Prepareし、前週の保存済み実行計画の終端BESS残量を次週へ渡す経路を実装した。物理・会計・168時間の全通過と672区間traceが欠ければ次週求解前に停止する。実行CLIも既存SQLiteの共有Gurobi枠・ローカル資源枠を予約し、単一Env再利用と各Modelの解放を行い、終了後の解放待ちを330秒保持する。関連回帰70件通過。現時点で2週求解の結果はなく、旧12週を連続運用証拠へ読み替えない。これはBESS在庫だけの引継ぎであり、ICE燃料など全車両状態の長期連続運用証明ではない。受電設備は仮値、fleetは承認前の候補である。

対象は現行 `main` からの開発変更である。既存12週の出典は固定 `7cb468942d9ec2526d8afc92dc3fa8b7c51b56eb` であり、今回の変更を適用して再計算した結果ではない。旧結果は引き続き `DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS` とする。

| 論点 | 今回確認・実施したこと | 残る採用条件 |
|---|---|---|
| GA・ABC部分MILP | 外側の残り壁時計、累積repair残量、1回上限の最小値を子MILPへ渡す。予算0ならMILPを起動しない。親の研究・threads・fallback禁止制御をそのまま渡し、子の実効Configは既存の`replace`経路で継承する。 | 時間上限は子ソルバーの設定値であり、モデル構築や外部ライセンス待ちを強制中断するOS締切ではない。正式実行で壁時計・中断を別途検証する。 |
| 受電設備 | `depot_power_limit_kw`を従来の課金基準に保ち、任意の`physical_grid_import_limit_kw`を設備の絶対上限として追加。前日・固定配車充電・recourse・rolling予備・実行再生・物理検証へ反映。未設定なら旧条件。例示の500 kWは診断仮定であり、営業所の設備値ではない。 | ユーザー確認では現行値は仮値。本番研究用の連続受電上限と設備資料を得て、同一固定条件で新規Prepareと正式実験を行う。現行12週の最大値が設備内だとは主張しない。 |
| fleet | 12週のprepared原本をSHA照合して同一scopeで`resolve_scenario_fleet_contract(..., research_run=True)`を実行。全月で同じ60台（BEV35/ICE25）、契約hash `d09cea1dd2e60416132636fc8b9e8176ef8698053f1265586e53ff7b0d29fff4`。 | ユーザーは現行台帳を正式候補として確認すると回答。承認者・承認証跡は未指定のため`CANDIDATE_NOT_APPROVED`。正式契約としては未採用。 |
| 第三者検算 | `output/research_review_bundle_20260923/monthly_evidence_bundle.zip`に12週×5原本、監査JSON、固定SHAのsource tar、相対パスmanifest、候補fleet、標準ライブラリのみの検証器を収録。原本・source・manifestのSHA、会計費目合計、選択した電力流量を再検算した。ZIP SHA `f901536957f22019ffedb7d9765295c277fefed6a466786521f6ecac85e5b4b9`。公開Gitやメールには送っていない。 | 同梱検証器は全便接続・全SOC・最適性を独立再実装していない。教員が原本を閲覧できる共有範囲を決め、別環境で全物理検証も再実行する。 |
| BESS連続週 | `check_bess_week_continuity.py`で既存12週の暦上の隣接と終端→次週初期の一致を評価。隣接週0組で`CONTINUITY_NOT_ESTABLISHED`。各週の初期3,000 kWhへのリセットを長期節約として合算しない。 | 連続する2週以上を同一clean固定版で新規に解き、週1終端SOCを週2のprepared初期SOCとして渡し、各15分の収支・充電可能性・会計を監査する。追加の終端復元を主条件へ戻さない。 |
| 分散実機故障 | `desktop-6ae0mir`へのSSH実疎通を確認。独立したsolver-free Python子プロセスの起動応答を確認後に親機SSHクライアントをkillし、再接続して完了マーカーを確認。証拠は`output/research_review_bundle_20260923/ssh_disconnect_trial_v3/result.json`。 | 従機は親機とコード・Python依存が一致せず`can_run_diagnostic=false`。既存キューを迂回して研究ジョブは投入していない。worker受理応答消失、親機アプリ再起動、従機再起動、重複通知とreconcileは実機未検証。親機＋1台のclean release・環境一致後に順次実施する。 |

実機故障試験の最初の試行はPowerShell経由でPython `-c` の引用符が失われ、子プロセス起動前に失敗した。原ログを保持し、Pythonコードを従機の一意な試験ディレクトリへ書いて起動する方式へ変更した。2回目の通過を1回目の成功として数えない。

この段階で言えるのは「旧12週の原本を持ち運んで限定的に再計算できる」「物理上限の仮定を課金基準から分離した」「SSH切断後の小さな子プロセス存続を実機で見た」である。統合最適性、連続週の持続運用、実設備適合、正式fleet承認、11台無人分散運用は未証明である。

再検査の入口（solverやGurobi不要）:

```powershell
python tools/research/verify_monthly_evidence_bundle.py output/research_review_bundle_20260923/monthly_evidence_bundle.zip
python tools/research/check_bess_week_continuity.py output/research_review_bundle_20260923/monthly_evidence_bundle.zip
```

前者は12週で`PASS`、ZIPのCRC検査は68項目すべて読取可能。後者は意図どおり`CONTINUITY_NOT_ESTABLISHED`を返す。ZIP内の同名Pythonファイルを取り出せばリポジトリがない別PCでも同じ限定的検査を実行できる。設備上限は各15分区間の平均受電kWに対する仮定であり、瞬間ピーク・変圧器の温度定格等を証明しない。
