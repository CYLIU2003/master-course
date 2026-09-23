# 分散ジョブ管理の引継ぎ（2026-09-23）

## 実行経路と確認結果

- 画面の計算先選択 → `/api/cluster/jobs` → 既存の最適化Prepare/凍結 → SQLiteキュー → 資源・担当・共有Gurobi予約 → 固定SSH先のrunner → 成果物SHA-256照合、を追跡した。
- 固定配布先の担当不一致は親ジョブ作成前にHTTP 409で拒否する。画面でも担当外を選べない。子機の役割は親機SQLiteに残る。
- 通信断後の `LOST` は自動再投入しない。子機の開始記録がないときだけ原子的な試行ID封止を受けて `BLOCKED`（未開始）とし、未使用の子機・Gurobi予約を解放する。開始済みは同じ試行の成果物を照合し、開始途中や通信不能は予約を保持する。再試行は別IDに限る。
- 共有Gurobi枠は総数2・外部予約1の設定で、分散キューは同時最大1枠。未開始と確定した試行にはWLSトークン冷却を課さない。Gurobi能力未登録機へのライセンス起動試験も投入前に拒否する。
- `BLOCKED` の未開始試行に成果物ZIPリンクを表示しない。遅延投入のエラーは確定済みの親機表示を `LOST` に戻さない。

## 検証と稼働版

- 自己レビューで見つけた重要な運用欠陥（投入前SSH断で予約が解放できない経路、端末能力に合わないライセンス試験、未開始ジョブの成果物リンク、遅延エラーによる表示上書き）は修正済み。独立レビューおよび研究採用の承認は未取得。
- 関連Python試験88件、画面試験16件、本番ビルドが通過。バックエンド固定版 `e301abbdc6b46331013de6c921a2a56427c5c14b` を18/18台へ照合配置し、親機の常駐設定を `output/cluster-deployment/onboard-20260923/controller-worker-fence-e301abbd-settings.json` に切り替えた。
- 実機では `DESKTOP-5B6F6BP` への診断ジョブ `fd0b0418-6692-4169-b792-6d98c19321e0` が `COMPLETED`、成果物ZIPのSHA-256が一致。同じ子機で未開始試行 `fence-audit-e6b87cdba896413cbb699f6022d908ea` の封止後、遅延投入の拒否を確認。監査値は `output/cluster-deployment/onboard-20260923/activation-worker-fence-e301abbd-audit.json`。
- 再起動後の親機は18台を監視し、Gurobi担当5台 `READY`、ALNS担当13台 `SSH_READY`。実行中ジョブ0件。配置・疎通・診断は実便最適化の成功を証明しない。

## 別タスクへ渡す未完了事項

- `alns_no_gurobi_v1` は単日・BESSなし・Rollingなしの診断専用。7日間・時間別Rollingと天候曲線の拡張には別の求解・状態引継ぎ・物理検証・会計・受理契約が必要。
- `DESKTOP-3PRU7QP` はWLS資格情報を本人専用アカウントに置いたが、実起動が `10009 License has expired`。登録本人の更新と新しいEnv/Model試験が通るまでALNS担当とする。
- `LAPTOP-BOLC6VIT` は直近空きRAM約0.4 GB。必要RAMとOS用予約を満たすまでは実便を割り当てない。
- 固定版での18台実便最適化、168窓Rolling、研究受理、独立レビューは未実施。古いSHAの出力を新固定版の成果と扱わない。

## 次の作業の基準ブランチ

- 次の7日間最適化・天候曲線拡張は `codex/worker-sort-passmark-20260923` の現在のHEADを出発点とする。配置済みの実行コードは上記 `e301abbd` であり、文書更新後のブランチHEADとは区別する。
- リモートにはこの基準ブランチと `main`、公開中のPR #8のhead `research/thesis-weather-results-bb0c005` とbase `research/weather-dispatch-diagnosis` を残した。ほかの7ブランチのリモート参照は整理済みで、対応するローカルブランチは保持している。
- `C:\master-course` の `codex/research-gates-20260923` には別作業の未コミット変更がある。基準ブランチへ黙って取り込まず、必要な変更だけ内容を確認して移す。
