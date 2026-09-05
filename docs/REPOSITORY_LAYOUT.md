# ファイル配置と保管ルール

2026-09-05整理。作業前HEAD: `c0b82ae30e874f65fabcfec94599982023bc3ca6`。
既存の未コミット変更を保持し、solver・GitHub機能は実行していません。

## 探す場所

| 内容 | 場所 | 取扱い |
|---|---|---|
| 起動・利用案内 | [ルートREADME](../README.md)、`run_app.py` | 利用者向け入口はルートに維持 |
| 最適化モデル | `src/` | この整理で数式・制約を変更しない |
| UI・API | `app/`、`bff/` | モデルと分離 |
| 正式実験・監査CLI | [scripts案内](../scripts/README.md) | ハッシュ・コマンド参照を保つため現位置を維持 |
| 補助ツール | [tools案内](../tools/README.md) | 目的別のサブフォルダへ配置 |
| 通常の回帰テスト | `tests/` | 手動solver実行とは分離 |
| 研究状況・正式手順 | [blocker](notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md)、[runbook](notes/FORMAL_RUNBOOK_CURRENT.md) | 現行の判断基準 |
| 進捗・発表資料 | [outcome](../outcome/README.md) | 元資料と日付別成果物を保管 |
| 過去の設計メモ | [archive](archive/implementation_notes/README.md) | 過去の提案を現行仕様と混同しない |
| 凍結根拠・執筆資料 | `docs/evidence/`、`docs/thesis/` | manifest対象のパスと内容を固定 |
| 実行結果・Prepare | `output/` | ignoredでも削除可能とは限らない |
| 旧実行結果 | `outputs/`、`results/` | 既存参照があるため保全。新しい出力先とは区別 |
| 原入力・文献 | `data/`、`scenarios/`、`先行文献/` | 一時ファイル扱いで削除しない |

## 今回移動したもの

- `tools/benchmark_api.py`、`benchmark_bff.py`、`benchmark_catalog_ingest.py` の本体 →
  `tools/benchmarks/`。旧パスはmodule alias兼CLI入口として保持。
  移動に伴うリポジトリルート計算を修正し、APIの新規生成レポートには新パスを記載する。
  既存の性能レポート・過去の開発記録の旧パスは互換入口へ解決するため変更しない。

- `test_multiday_phase1.py` の本体 → `tools/manual_experiments/test_multiday_phase1.py`。
  ルートには直接実行時のみ委譲する互換入口を残した。
- `analysis_multiday_plan.md`、`experiment_logger_integration.md` の本文 →
  `docs/archive/implementation_notes/`。旧パスはリンク案内として維持。
- 作業領域の `package_manifest.mjs` →
  `tools/thesis_authoring/maintenance/package_august_20260905.mjs`。
  固定日付の梱包処理として隔離し、汎用CLIとは扱わない。

## 削除と保全

8月スライドの `pre_copy_fit*`、`pre_layout*`、`.chart-data-*` は中間生成物として
削除候補にしたが、削除コマンドが実行環境のポリシーで拒否されたため残している。
今回、ファイル削除は実施していない。`nul` も未削除である。
その他の `tmp/` にも過去の診断・監査記録があり、フォルダ名だけでは削除しない。

公開済みPPTX、文献PDF、Outcomeのmanifest/inventory、凍結raw結果、prepared input、
ハッシュ対象の既存作成スクリプトを変更しない。
`experiment_logger.py` はBFFとテストから直接importされているためルートに保持する。

今後の一時描画は `output/<用途>_<日付>/`、再利用する作成処理は `tools/<用途>/`、
配布物は `outcome/<日付>_<用途>/` に置く。正本のreceiptとハッシュを確認してから
中間生成物を整理する。過去の実験記録中のパスは履歴として書き換えない。

## 検証結果

追加整理後は関連テスト32件PASS（移動した入口のimport安全性・委譲、案内リンク、README、
両進捗資料、logger）。凍結 `weather_dispatch_rerun_bb0c005` の厳格なbundle検証もPASS。
`git diff --check` はPASS。全テスト・solver再実行は実施していない。
カタログ計測の旧・新CLIは両方 `--help` を確認済み。API/BFF計測本体は実行していない。
