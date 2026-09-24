# 渋21〜23：週次成果を優先する実行手順

2026-09-24のユーザー訂正を適用する。厳密最適性の証明を全ケースの開始条件にせず、
運行・エネルギー・費用が成立する週次結果を先に揃える。旧判定と原本は上書きしない。

## 今回得られた成果

原実行SHA `7cb468942d9ec2526d8afc92dc3fa8b7c51b56eb` の12週を再照合。
各週1,704便、13,925.428829営業km（地理的代理距離）、168時間・672区間。
週費用は7月4,153,640.193807円〜3月4,873,779.232267円。
車両使用費は410万〜412万円/週。買電・契約超過費等と合わせて解釈する。
旧BEV終端は初期残量への復元であり、新しい翌朝SOC上限条件とは比較版を分ける。
季節差は電費一定・各月1週の条件差であり、HVACの季節効果、PV単独の因果効果、年平均ではない。

親機出力 `C:/master-course/output/weekly_seasonal_20260924/results/` に、週次・日別CSV、
原本参照、全便の車両割当、全BEVの保存SOC、BESS在庫、充電表、需給図と日本語考察を保存する。
日別費用は原実行台帳の配賦を保持。元の研究判定はDIAGNOSTICのまま、条件付き週次評価を追加。

## 成果を止めていた箇所だけ修正

渋21 v4の週次試行はメモリ不足ではなく `TIME_LIMIT_NO_INCUMBENT`。
Stage1=1,800秒の要求に対し、共有予算が120秒で、構築233.8195秒後に求解予算が残らなかった。
新しい三路線キャンペーンは共有7,200秒、Stage1=1,800秒、Stage2/各rolling窓=600秒、
4threads、1%目標、既存のbarrier/no-crossover profile（soft18GB）を宣言する。
共有予算は最初の前日計画の構築・段階間で共通であり、週全体のwall時計ではない。
各rolling窓の構築や保存を含む総所要時間はこれより長くなる。元の120秒を黙って別解釈しない。

既存の厳密な帰庫接続因子と充電窓端点表現が、BFFからsolver metadataへ渡らなかった。
Preparedに明示されたboolだけを転送する。候補接続の枝刈り、便削減、SOC緩和は追加しない。
実行中の固定版には適用せず、新しいclean SHAと新規Prepared/attemptで使用する。

## AIなしでの通常処理

既存原本の再集計（最適化・ODPT通信なし）:

```powershell
python tools/research/weekly_results.py --verified-report C:/master-course/output/weekly_seasonal_20260924/reverified_monthly.json --output C:/master-course/output/weekly_seasonal_20260924/results
```

固定された三路線の元データを最適化DBへ手動変換:

```powershell
python tools/research/weekly_campaign.py freeze --source output/shibu21_23_exact_20260911/source_candidate --output data/optimization/shibu21_23_frozen_20260924
```

この変換は全16路線パターン・648テンプレートを保存し、原本の4項目hash・全行を検査する。
ネットワークからの自動取得はない。既存DBと内容が異なる場合は新しい保存先を使う。

実行は `tools/cluster/release.py` と `serve_controller.py` の既存方式でclean固定版を配布した後、
コントローラーと同じ `MC_OUTPUTS_DIR` / `SCENARIO_STORE_PATH` / `BUILT_ROOT` を設定して行う。
元シナリオは専用storeへ実体化し、親の設定hashを固定する。週次インスタンスはそこに保存し、
ユーザーの基本シナリオを月ごとに書き換えない。

```powershell
python tools/research/weekly_campaign.py run --settings <controller-settings.json> --output <campaign-directory> --workers desktop-6ae0mir local
```

`--workers`はその時点で実ライセンス試験とRAM要件を満たす端末を指定する。
各週を独立投入し、1件の失敗で他の週を取消さない。PC不明/SSH切断は既存attempt照合を継続する。
既存brokerを共有し、別コントローラーで同じライセンス枠を二重管理しない。
親機にも週次計算を割り当てるが、OS等の余裕と最低空きRAMをschedulerで検査する。

回収後は既存archive監査を実行し、確定rolling会計・全便・7日＋翌朝の区間数・日別台帳・電力を照合。
成功した週から `results/` にCSV/図を生成する。原本ZIPと元判定は保持。
状態は `state.json`、各週の `batch.log` と `artifact-audit.json`、管理画面のジョブ詳細で確認する。
ローカルobserverは30秒ごとに状態を見るだけ。終端時だけ既存Codex通知経路から承認済みGmail送信へ渡す。
メール自体はOAuth/Gmail接続が必要であり、Python単独送信可能とは説明しない。

## 比較条件と残件

高PV候補771d115bと低PV候補b23fd26cは同じ車両・設備だが単一日のPV参照が違う。
両方を同じ実PV週へ置き換えると同一条件になるため、二シナリオの週次化を勝手に作らない。
確認できた基準構成の四季計算は先に進める。

設備の物理受電上限・費用根拠・正式fleet承認・地理的代理距離の限界は残る。
最適性が未証明でも条件付き費用を示せることと、正式研究採用が承認されたことは別。
今回のコードの独立レビューおよび新版7日完走は、実測が得られるまで未確認として記録する。
