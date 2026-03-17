# Core Review Note

このファイルは簡易メモです。core の正本手順は README.md を参照してください。

## coreの前提

- 実行導線は Tkinter と BFF のみ
- 東急全体最適化を再現できる最小構成
- 最適化入力パラメータは削除しない

## 主要参照

- 実行手順と検証: README.md
- 制約定式と実装対応（C1-C21, 記号表付き）: README.md の「10. 先生レビュー用: 最適化定式と実装対応」
- パラメータ保全: docs/core_parameter_preservation_manifest.md
- 非Tkフロント機能の移植バックログ: docs/tkinter_feature_parity_backlog.md
- 最終検証レポート（3→2→1）: docs/core_final_validation_report_20260317.md

## レビュー時の観点

- Dispatch feasibility が崩れていないか
- Solver mode/objective/penalty/tariff の契約が保持されているか
- Tkinter で prepare と optimization が完走するか
- MILP/ALNS/hybrid architecture adequacy
- experiment reproducibility and reporting integrity

This document is meant to be sufficient for independent setup and technical review without prior project context.
