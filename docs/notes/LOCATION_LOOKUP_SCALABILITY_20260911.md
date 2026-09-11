# 完全接続検証の地点照合キャッシュ

## 問題と変更

渋21〜24の7日・3,182便を完全Prepareする過程で、同じ停留所の別名展開と回送・折返し照合が便ペアごとに反復されていた。凍結SHA `737e07be` の実行スタックを1回観測し、`DispatchContext.resolve_location_ids` → `get_deadhead_min` → `FeasibilityEngine.can_connect` → `ConnectionGraphBuilder.build` にいることを確認した。

`src/dispatch/lookup_snapshot.py` は1回の計算で使用するルール・aliasのコピーを作る。位置解決、回送時間、基本折返し時間、地点同値、地点データ有無の5種類を各4,096件までキャッシュする。上限到達時は古い項目を除外し、必要なら元の関数で再計算する。キャッシュは呼出し間で共有しない。

使用範囲は全接続graphの生成、strict coverageの遷移監査、path-cover matchingの費用行列作成である。元のDispatchContext、カスタムcontextのメソッド、元データの可変性を保持する。次の計算では最新のルールと折返しbufferを読み直す。

## 数学・比較可能性

候補ペアの生成数・順序、接続可否を計算する元関数、`arrival + turnaround + deadhead <= next departure`、日次帰庫、車種互換性、拒否理由を変更していない。時刻表・operator・距離量・SOC・料金・フリートへの変更はない。後続候補を間引くpruningではない。

多日・路線固定ON/OFF・alias cycle・Unicode表記・欠損回送のケースで、キャッシュを使わない `analyze()` の全候補から抽出した接続一覧と一致した。strict coverageでは車両下界・便ペア件数・全拒否理由サンプルがキャッシュなしと一致した。ルール更新・alias変更・折返し感度条件をまたいで古い値を流用しないテストも通過した。

## 実入力由来の局所測定

元実行から地点照合だけを観測した `output/four_route_runtime_observation/lookup_inputs.json`（SHA-256 `27d37dedc2fb40fb7814bd312b9442981cc98a3ffaad42076053d5485a9e7bc0`）を使用した。このファイルはsolver入力や実験結果ではない。17地点・289組の全結果とalias展開の順序を比較し、すべて一致した。

`benchmark_location_lookups.py --repetitions 1000` の289,000組の反復は、従来4.8137秒、キャッシュ0.3466秒、比率13.89倍だった。`lookup_benchmark_v1.json` は実装中のdirty計測であることを明記している。照合の反復部分だけの測定で、context生成、全graph生成、メモリー全量、solver実行は含まない。全診断時間の改善率とは呼ばない。

```powershell
python scripts/benchmarks/benchmark_location_lookups.py --input output/four_route_runtime_observation/lookup_inputs.json --output output/four_route_runtime_observation/lookup_benchmark_new.json --repetitions 1000
```

## 検証とレビュー

- 関連dispatch/strict/route-band検証: 41 passed。
- 全体: `python -X utf8 -m pytest -q`、2,034 passed / 2 failed、90.09秒。失敗は既存のPowerPointハッシュ・部品同一性の2件。
- Reviewer: GPT-5.6 Luna。Date: 2026-09-11。対象は新lookup helperと3つの呼出し箇所。P0/P1指摘0件、対象6テスト成功。これは研究モデル全体の採用レビューではない。

旧作業フォルダーのソースと成果物を保持し、新しい凍結SHAでは完全Prepareから別出力へ再実行する。旧SHAの成果物を新SHAの証拠へ付け替えない。
