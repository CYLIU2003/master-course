# EV Bus Research desktop

TypeScript + React + Electron のデスクトップアプリです。Python/FastAPI をローカルの子プロセスとして起動し、既存の Prepare・最適化・ジョブ API を使います。

## 起動

Python 3.11 以上の `.venv` と、このリポジトリの入力データ・依存ライブラリが必要です。Node.js は Vite 8 が対応する版を使ってください（この環境では Node 26.8.2）。Gurobi の利用には別途既存のライセンスが必要です。

```powershell
cd C:\master-course
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm.cmd ci
npm.cmd run build
npm.cmd start
```

ビルド済みなら、リポジトリの `python run_desktop.py` でも起動できます。

Windows portable 版は `npm.cmd run package` で `release/EV Bus Research 0.1.0.exe` に生成します。初回に研究リポジトリのフォルダーを選択してください。**この exe は画面と Electron を含みます。Python・Gurobi・研究データは選択したリポジトリの環境を使用します。** 現在のローカル版にはコード署名を付けていません。

設定済みのフォルダーを変更する場合は、起動するプロセスに `EV_BUS_WORKSPACE` を指定します。Python 実行ファイルを変更する場合は `EV_BUS_PYTHON` を指定します。パスや認証トークンを React に公開する IPC はありません。

## 画面でできること

シナリオを選び、左メニューから運行・計算設定、車両、営業所・充電設備、路線、
PV・BESS、気象、データ、実行、図表、比較を開きます。

車両・テンプレートの作成/編集/複製/一括変更、設備と料金・SOC・solver設定、
気象CSV/JSONの取込みと予報生成、時刻表の検査付き置換・全行書出し、
calendar/permissionの編集、Prepare/最適化/simulation/再最適化/rolling、
車両ダイヤ・SOC・電源フロー・費用明細・保存レポートの取得に対応します。
[操作別の対応表と制限](../docs/notes/DESKTOP_TK_PARITY_20260911.md)。

未保存の変更は各画面に保持します。シナリオ切替・実行の前に保存か「元に戻す」を
選びます。保存済み条件が別操作で変わった場合は再読込みと再Prepareが必要です。
Prepareは派生データを更新します。以前の結果を残す場合はシナリオを複製してください。
BESSの20〜80%ボタンは日末・週末の残量を範囲内で自由にします。BEVの条件は維持します。

研究採用・物理検証・最終会計・最適性は別に確認します。未確認を合格やゼロにしません。
旧Tkinter入口と研究成果物は保持し、全Tkinterメニューとの逐語的な一致は主張しません。

## 検証・型生成

```powershell
npm.cmd run api:generate
npm.cmd run typecheck
npm.cmd test
npm.cmd run smoke
```

OpenAPI から `src/generated/api.ts` を生成し、公開 DTO をそこから参照します。任意 JSON の内容は `unknown` として境界で確認します。`api:generate` の Windows コマンドは `.venv/Scripts/python.exe` を使います。他 OS では同じ `scripts/export-openapi.py` を対応する Python で実行してから `openapi-typescript` を呼びます。

Smoke は別の Electron セッションで全メニューと900px幅を確認し、`output/desktop-smoke/` に記録します。シナリオの書換えやsolver実行は行いません。保存済み結果がある場合は既存ファイル1件をsmoke出力フォルダーへ取得し、native downloadも検査します。`EV_BUS_SMOKE_SCENARIO_ID` で検査するシナリオを指定できます。Electron を閉じると、起動した BFF へ停止を要求し、5秒で終了しない場合はその子プロセスツリーだけを終了します。最適化中はアプリを開いたままにしてください。

2026-09-11、GPT-5.6 Lunaが `electron/main.ts` と `bff/desktop_server.py` を独立して確認しました。loopback限定・Bearer認証・起動応答のHMAC・protocol/path分離・sandbox/contextIsolation・stdin終了監視・Windows子プロセス終了が対象で、P0/P1指摘0件。画面全機能や研究モデル全体を承認するレビューではありません。

## 大量データへの対応と測定範囲

API は1ページ最大250件に制限し、React は見えている行と前後の行だけを描画します。検索とページ要求はキャンセル可能です。Parquet は先行 row group を飛ばし、新規保存は16,384行単位に分割します。SQLite の時刻表ページと件数は同じ読取りトランザクションで取得し、全時刻表を Python に展開しません。既存の重複行の表示規則を維持します。

結果 JSON と SQLite の TEXT blob はストリームで必要な検証値だけ読み取り、ファイル変更時刻・サイズでキャッシュを更新します。大きすぎる検証要約は明示的なエラーにし、切り捨てて採用判定を変えません。旧 JSON 形式の入力は互換の読み方が残るため、全件ロードが必要になる場合があります。

旧結果の裸 `Infinity` / `-Infinity` / `NaN` は表示専用readerで文字として保持します。原本を書き換えず、非有限の最終会計は「未確定」のままです。2026-09-11の修正後再測定はSQLite1.20秒、Parquet0.0082秒、36 MB結果5.73秒、キャッシュ後0.00098秒、Python読取り割当2.1 MB以下でした。[互換性検証](../docs/notes/DESKTOP_LEGACY_JSON_COMPATIBILITY_20260911.md)。

100万行の合成データで末尾250行の正確さとゼロ値の保存を確認しました。時刻表254.6 MBに対するページ取得は1.27秒、Parquetの末尾ページは0.013秒、36 MBの結果初回投影は5.72秒、キャッシュ後は0.0011秒でした。Pythonの読取り時最大割当は2.1 MB以下でした。**SQLite/Arrowのネイティブメモリーとデータ構築はこのメモリー値に含みません。** solver 本体のメモリー・計算量を無制限に扱えるという意味ではありません。

再実行: `python scripts/benchmarks/benchmark_desktop_reads.py --rows 1000000`（リポジトリルート）。新しい合成出力フォルダーを作り、実際の研究入力は使用しません。

## 境界と変更記録

Electron は sandbox・contextIsolation を有効化し、nodeIntegration を無効化します。React は `research://app` の同一オリジン API だけを使い、main process が起動ごとの認証を付与します。BFF は `127.0.0.1` の動的ポートに限定し、起動応答の署名も確認します。外部遷移・新規ウィンドウ・権限要求は拒否します。

設計根拠: [Electron security](https://www.electronjs.org/docs/latest/tutorial/security)、[Vite guide](https://vite.dev/guide/)。Tkinter・既存 API・数理制約の互換性を保つ方針です。デスクトップの検証通過は研究採用の承認ではありません。
