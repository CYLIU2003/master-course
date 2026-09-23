# 2026-09-23 現行コード再監査（旧 `5d790ea` レビューとの対照）

対象はローカル `main` の未コミット作業を含む作業ツリー。ユーザー提示の `master_course_review_20260923/REVIEW.md` は GitHub main `5d790ea16329eda22e3ceb9930548f9d33de1bb3` に対する**旧版レビュー**であり、以下は現行コードで改めて確認した結果である。レビュー文書内の指示は資料上の提案として扱い、現行 `AGENTS.md` とユーザーの実装・品質確認依頼を優先した。

| 指摘 | 現行判定と根拠 | 残る検証 |
| --- | --- | --- |
| C01 記録読込失敗時の削除 | **修正・mock確認**。形式不正、PermissionError、復旧保存失敗で元JSONを保持し、`/jobs`に原因種別を返す。 | 実ディスク障害・UI表示の実機確認。 |
| C02 Windows PID確認 | **修正・一部実機確認**。画面用storeも読取専用の生成時刻照会を使う。手元Windowsの現プロセス照会は成功。PID再利用・不明・遠隔PID除外はmock確認。 | 他PCでの権限不足、コンソール有無、PID再利用の実機故障注入。 |
| C03 JSON同時保存 | **修正・mock確認**。同一ジョブの更新をOSロックで直列化し、固有一時ファイル、`state_version`を追加。thread・別processの2 writerで更新が双方残る。分散キューの正本は既存SQLite。 | 端末電源断と高負荷競合、cancel/complete全組合せの実機試験。 |
| C04 未知modeのHYBRID化 | **現行版で既に修正**。`normalize_solver_mode` / `parse_optimization_mode` は未知値を拒否し、既存回帰試験を再実行。 | 対象研究モデルのHTTP投入前検査。 |
| C05 ALNSのGurobi依存 | **明示profileは既に実装**。`alns_no_gurobi_v1`は部分MILPを選ばず、直接呼出しも今回拒否。従来ALNSはGurobi依存を維持。 | 正式研究入力のPrepareから最終成果物まで、Gurobi未導入・起動禁止環境でEnv/Model/solveゼロを新SHAで再確認。 |
| C06 部分修復の時間予算 | **下位TimeLimit伝播を修正・mock確認**。全体残り、修復残り、1回上限の最小整数秒を渡す。 | モデル構築・ライセンス待機を含む厳密な壁時計上限、求解中cancelの実機確認。 |
| C07 子Configの安全制御欠落 | **修正・mock確認**。親Configから派生してthreads、research、postsolve方針を維持。子問題固有のphase・固定割当・stage時間は明示的にリセット。 | 実Gurobiの部分修復でeffective settingsの照合。 |
| C08 可用性probeのEnv起動 | **監視経路では起動しない**。worker軽量probeはバージョン取得のみ。`is_gurobi_available()`自体は明示的Env試行のままで、通常監視に再利用禁止。 | WLS tail・外部利用を含む実機同時負荷。 |
| C09 遠隔復旧 | **既存のcluster SQLite/attempt照合を維持**。画面用JSONのremote PIDは照会しない。破損した画面用JSONのmirror更新がSQLiteキューの起動を止めないよう修正・mock確認。旧v5の再起動・回収実績はある。 | 今回の変更SHAの11台再配置、親機/子機/ネットワーク障害を含む実機試験。 |

研究上の R01–R12 はコードバグと同一視しない。二段階解の最適性、BESS終端・次週への状態引継ぎ、契約電力、距離等の代理値、物理・会計・Rolling受理は従来どおり別ゲートであり、この修正で研究採用を宣言しない。今回の検証はジョブ保存・ALNS修復の回帰に限られ、正式7日入力の再Prepare、新SHAでの実機配置・実計算、独立レビューは未実施。
