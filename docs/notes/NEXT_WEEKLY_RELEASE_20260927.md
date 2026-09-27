# 次回週次計算向け配布候補の確認

2026-09-27。計算候補は固定 `267e33eb4f347c5d1b0fa6c8894a972d925642d2`。
稼働中の11月は `f524eca2` の同じ試行を継続する。本記録はオフライン配布検査であり、配置・求解・研究採用の完了記録ではない。

## 今回用意したもの

すべて `C:/master-course/output/cluster-deployment/` 以下。

|場所|内容|
|---|---|
|`release-next-267e33eb/`|clean・detachedの独立clone。Git worktree参照や外部objectsへの依存なし|
|`package-next-267e33eb/release.json`|コード、ZIP、選択データセット、依存定義の正確なhash|
|`package-next-267e33eb/267e33eb4f347c5d1b0fa6c8894a972d925642d2.zip`|既存release.pyで生成した配布候補|
|`package-next-267e33eb/roundtrip/`|既存stage_release.ps1でローカル展開して照合したコピー|
|`frontend-next-267e33eb/`|同じ固定cloneでTypeScript・Vite・Electron TypeScriptのbuildを通した静的画面|
|`package-next-267e33eb/verification.json`|今回の確認結果と未検証範囲|

ZIP SHA256: `f864fee36edfff92f0ce521a480b998cb7616a15571849fd10a5078b82475019`。
展開前後のtracked 2,036ファイル、bff/srcのsource_digest、Git SHA/clean状態、選択データセット8ファイルが一致した。
データは稼働固定版の `data/built/tokyu_full` をhash照合して複製したもの。ODPTの取得・DB再生成は行っていない。
この8ファイルの一致だけで、シナリオ・Prepared・PV等の全実験入力を確認済みとはしない。

展開後のworker probeを実行し、Gurobi Env/Model/ライセンスprobeへ入ると失敗する検査で呼出し0件を確認した。
これはインストール版とホスト情報の読取であり、ライセンスが利用可能という判定ではない。
frontend依存は既存lockとローカルnpm cacheから `npm ci --offline --no-audit --no-fund` で準備。
ビルド成功は新画面の本番配信・ブラウザ操作確認を意味しない。設定の実ブラウザ確認は別記録
[ROLLING_SEARCH_COMPARISON_20260927.md](ROLLING_SEARCH_COMPARISON_20260927.md) を参照する。

## 切替時に見つかった注意点

旧版のuv.lockはCRLF、新cloneはLFだった。改行を除く内容とインストール済みPython/依存パッケージ版は同じだが、
正確なbyte hashは旧 `6517e0c5…` と新 `08dadc7b…` で異なる。照合の無効化・正規化で通す修正は行っていない。
新しいcontroller設定は新releaseの `runtime_versions` とsource_digestを使い、workerも同じ新releaseで照合する。
旧controller-settings.jsonへ新repoパスだけを差し替える操作は不適切である。
今回のruntime読取は親機のcontroller-venvであり、各遠隔PCのパッケージ実体・ライセンスは未検査。
`production_source_unchanged` は親機上の旧固定releaseをsettings記録のhash/SHAと再照合した意味で、遠隔実行中メモリの証明ではない。

## AIなしの再検査

既存のローカル候補を再検査する。配布、Prepare、ジョブ投入、コントローラーの再起動は行わない。

```powershell
& C:/master-course/output/cluster-deployment/controller-venv/Scripts/python.exe -X utf8 `
  C:/master-course/output/cluster-deployment/package-next-267e33eb/verify_offline.py
```

成功時は `OFFLINE_VERIFIED_NOT_ACTIVATED` と表示される。現在の旧版設定・releaseを保全したことも照合するため、
将来コントローラーを切り替えた後は当時の状態確認用として使う。失敗を無視して続行しない。

## 次に行う順序

1. 現在の12週を同じ試行から回収・検算する。11月のPID・生成時刻を照合し、不明な予約を解放しない。
2. 新版は既存 `tools/cluster/release.py stage` を使い、適格PCの別SHAディレクトリへ配置する。
   新しいprivate configを生成し、実機のsource/runtime/dataset照合が通るまでは新規投入に使わない。
3. 稼働中controllerとは別の設定・入力版で、既存の操作入口から新規Prepareする。
   旧Preparedや旧day-aheadを新SHAの成果として流用しない。共有ライセンス管理を別キューで複製しない。
4. まず同条件の1週で、全便・翌朝を含むSOC・電力収支・最終会計・実時間・メモリを検証する。
   探索方針の既定は `feasibility_first` を維持し、`bound_first` は明示的な比較設定とする。
5. 検証後に本番操作入口を切り替える。元の11週の結果は元SHAで保持し、表示・集計だけの変更で再求解しない。

## 後続検証：空き機への配置と同条件Prepare

同日、親機と空き32GB機 `laptop-a709una0` の2台について既存release.py stageを実行し、
別SHAの配置先でGit/source/runtime/dataset照合が通過した。事前に予約0件・active_jobs空を確認し、
子機の直前試行も既存runnerのPID/生成時刻照合を通した終了状態だった。原FAILEDは保持した。
親機のdraining指定は維持。新private configは候補フォルダの`staging/verified.private.json`であり、本番へ適用していない。
稼働中の11月を担当する`desktop-6ae0mir`への配置・コード変更は行っていない。

新releaseで実際の3月代表週（2025-03-03〜09＋翌朝）を新規Prepareした。親シナリオは別保存先へ複製し、
SQLiteはread-only接続のbackupで取得、参照先を隔離保存先へ変更した。旧固定releaseの時刻表DB・祝日・Solcast・予測holdoutは
既存ファイルとのhash一致を確認して配置した。コードは前後267e33eb/clean。外部取得・Gurobi・投入は行っていない。
`prepare-march/verification.json`に新Preparedと入力コピーの記録を保存した。

Prepareは1,704便、fleet引継ぎと既存の厳格coverage/接続/折返し/適合性検査を通過。
旧3月Prepared原本のhashを確認し、新Prepared全体から次の管理情報だけを除いて完全一致を検査した：
`prepared_at`、`prepared_input_id`、`scenario_hash`、`scenario_id`、`scope_hash`、`scope.scenario_id`。
実行要求もprepared ID以外一致、翌朝条件・fleet契約も一致。比較対象モデル入力hashは
`3fdf134f6ba060d52c4a9adce832d5bdffbc52d530768bb30395ac5795368205`。
この照合は入力の同一性であり、新しい解の物理・会計成立や速度改善の証明ではない。

Claudeは複製元scenario全ファイルの前後hash検査不足を指摘した。この実行ではmetadata前後のみを確認しており、
元artifactの全byte不変証明には使わない。研究入力については上記の旧Preparedとの全体比較で同条件を確認した。
WAL未checkpointによるbackup漏れという指摘は、writerを開いたまま未checkpointのcommitを作り、read-only backupで
全行を取得する分離試験が通過したため、そのまま欠陥とは扱わない。新規出力先のみを許す仕様とgit statusでの
未追跡検出も維持し、自動削除・失敗出力の上書きは追加していない。レビュー原文と検査結果を保存した。

## 現在の未完了

本番8891への新画面・新controllerの切替、新版の1週求解と検算は未実施。
料金表cacheと同一検査内のtimeline再利用は局所計測・同一復元問題での一致を確認済みだが、週全体の短縮率は未測定。
オフライン配布検査を「高速化済み」「正式研究採用」「全PC無人完走」と読み替えない。

## 独立レビューの扱い

Claude Sonnetへ記録・検査コード・receiptを提示した。版混在とライセンス非取得の扱いは妥当との所見。
ただし「hashが65/66文字」「旧source照合のassertがない」という指摘は原本と一致しなかった。
Pythonで対象hashがすべて64文字であること、旧releaseのgit_state/source_digestのassertが存在することを再確認した。
`review-fact-check.json` とレビュー原文 `claude-review.json` を配布候補フォルダへ保存し、誤指摘を修正根拠にしない。
親機と遠隔PCの確認範囲は本文へ追記した。これは静的な独立レビューであり、新版の実機求解・全週承認ではない。
