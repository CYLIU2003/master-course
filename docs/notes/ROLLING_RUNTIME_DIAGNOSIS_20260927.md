# 毎時計算の時間内訳と次の高速化対象

2026-09-27。計算固定版 `f524eca2552a4386bd033a15bbe046c14dc09281` の保存原本を読取専用で測定。
これは高速化の効果測定でも、研究採用の再判定でもない。

## 確認できた時間

| 対象 | 保存窓数 | reoptimize呼出し合計 秒 | native optimize合計 秒 | その外側 秒 |
|---|---:|---:|---:|---:|
| 1月・回収済み | 175 | 13,626.309 | 12,287.740 | 1,338.569 |
| 11月・実行途中 | 51 | 18,996.682 | 18,576.140 | 420.542 |
| 12月・実行途中 | 102 | 16,182.329 | 15,073.540 | 1,108.789 |

11月・12月の読取時刻はそれぞれ19:21:47/19:21:54 JST。
処理中の窓を含まず、残りの所要時間を保証する値ではない。各原本に保存された窓を対象とし、件数を揃えるための削除や補完は行わない。

1月は呼出し時間の90.18%がnative探索。300秒を超える16窓のnative時間は9,102.62秒で、
全native時間の74.08%を占める。11月の保存部分は97.79%、12月は93.15%がnative探索。
全3対象で複数native終了行の窓は0件。まず長い充電MILP探索を対象にする根拠が得られた。

元の `stage2_runtime_seconds` はStage2 helperの開始からの経過時間であり、モデル構築・解抽出も含む。
これを純粋なGurobi求解時間とは呼ばない。新しい読取ツールはnative logの最終
`Explored ... in ... seconds` / `Solved in ... iterations and ... seconds` 行を使用する。
根LP・barrierの途中終了行は加算しない。同じ呼出し内の逐次再求解は累積時間として加算し、回数を別記する。

呼出しの外側にあるJSON保存、採用区間の実行再計算、最終集計はこの時間に含まれない。
差分時間は前処理・構築・抽出・検算の合計であり、すべてを構築時間とは扱わない。
ログ欠損は0秒にせず未確認とする。

## 追跡した経路

`bff/services/optimization_run/rolling_chain.py` →
`scripts/run_hourly_charging_reoptimization.py::run_rolling_chain` →
`RollingReoptimizer.reoptimize_charging_hour` → `OptimizationEngine.solve` →
`MILPOptimizer.solve` → `_solve_charging_only` → `_solve_thesis_stage2_charging_dispatch`。

固定配車のStage2は毎時モデルを構築し、現経路では充電計画のMIP Startを投入していない。
Stage1や統合モデルにある別のwarm-start処理を、ここで使用済みとは扱わない。
現行のNumericFocus、Presolve、Methodは過去の数値失敗への対策を含み、無根拠に戻さない。

## 次の改善と検証条件

最優先の候補は、既に得られた前日/前窓の充電計画を初期候補として使うこと。
これはまだ未実装・未求解であり、短縮を約束しない。

- 原本の固定配車・PV・料金・実行状態・窓末端条件を一致させた比較を作る。
- 将来の解や評価窓の最終結果を初期候補にして、有利な測定を作らない。
- `ChargingSlot`は電源別に分割されるため、同一車両・絶対slot・物理充電器で扱う。
  古いSOCや将来予測値を実行状態へ上書きしない。
- 初期候補はsolverへの提案であり、制約固定・fallback・postsolve repairにしない。
- 長い窓だけでなく短い窓も含めて、同一時間上限・threads・数値設定・対象PCで比較する。
- 実行可能解取得時間、終了時間、gapと対象、目的値、採用区間の独立物理・会計、ピークRAMを確認する。
  時間制限内の異なる可行解の目的値が完全一致することまでは要求しない。
- 既存2枠が実行中なので、現在の試行・予約を維持する。新しい固定版と空き枠で診断し、
  通過後に新規試行へ適用する。現在の2週を途中で別実装にしない。

## AIなしの再測定

```powershell
python -m tools.research.rolling_timing_report --run C:/path/to/saved/run --output C:/path/to/new/timing.json
```

`--run`は`rolling_hourly_chain`と`diagnostics`を含む回収済みrunフォルダ。
出力は原本の外側かつ新規ファイルだけを許可する。原本の絶対パスを辿らず、このbundle内のログを照合する。
各読取ファイルの相対パスとSHA256、窓ごとの時間、欠損・複数求解、遅い10窓を保存する。
ソルバー、環境認証、SSH、新規ジョブ投入を行わない。実行中workerへの今回の読取は一度だけの診断であり、追加監視ではない。

## 証拠と検証

- `output/rolling_timing_20260927/january-v2.json`:175窓と原本hash。
- 同フォルダ `november-live.json` / `december-live.json`: 同一attempt/manifest照合後の読取。プロセス生成時刻を含む既存読取でもPID8976/15808が実在した。
- `tests/test_rolling_timing_report.py`:16件。根LP除外、累積再求解、欠損、数値、窓ID、順序、不整合、原本内出力と既存レポート上書きの拒否を確認。
- Claude Code/sonnetによる独立の読取レビューと再レビューを保存。最初の「複数逐次optimizeの加算が二重計上」という指摘は呼出しの計測範囲と矛盾するため採用せず、再レビューで撤回された。
  複数求解窓の集計表示と窓ディレクトリの照合は追加。再レビューで当該ツールのP0/P1なし。
- ソルバー本体・物理条件・実行中worker・コントローラーの変更、追加Gurobi起動は0件。

この測定で計算そのものが速くなったとは主張しない。高速化対象がnative探索にあることを確認した段階。
