# 管理サーバー自動復旧の画面操作

2026-09-27、開発元03dea4c7。計算固定版f524eca2552a4386bd033a15bbe046c14dc09281は変更していない。

## 利用者の入口

http://127.0.0.1:8891/#cluster の「分散計算」上部から、自動復旧を有効／無効にできる。
PID、再起動回数、監督確認時刻、HOLD/BLOCKED理由を表示する。別の管理先は閲覧専用。
無効化は自動復旧のみを止める。求解や管理サーバーを停止せず、新しいattemptも生成しない。
既存キューの割当が復旧時に再開される点は従来どおり。任意コマンド、上限解除、記録消去の操作は提供しない。

## 配置

- supervisor_ui.pyを独立したloopbackサービスとして登録済みログオンタスクから起動。
- controller_supervisor.pyの既存lock、固定版照合、3回上限、同一queue復旧を再利用。
- 無効化中も操作サービスは継続し、再有効化できる。監督30秒、画面取得5秒。
- ポートごとのdiscoveryで対応を照合。サービス再起動ごとにnonceを更新し、操作直前に取り直す。
- APIはnonce、Host、loopback Originを検査。変更は対象controllerと同じポートの画面に限定。
- 稼働BFFは再起動せず、静的frontendのみ配置。旧監督を無効化して終了を確認後、同じタスクをUI対応版へ変更。
- 8868/8891で静的ファイルを共有するため、登録情報はsupervisor-control-<port>.jsonに分離。

## 検証とレビュー

- Python36件：同じ管理元での切替、別管理元の読取専用、外部Origin・nonce不一致・Host偽装・任意payload拒否、既存監督回帰。
- frontend14件（2ファイル）、TypeScript型検査、本番build通過。
- 8891の実画面ボタンをキーボードで操作し、無効→有効の永続状態と成功表示を確認。終了時は有効。
- 管理PID52332は前後で同一、全54job ID集合も不変。新規求解投入なし。
- 証拠：output/supervisor_frontend_20260927/verification.json、static-deployment.json、frontend-enabled.png。
- 標準PATHのPythonにはpytestがなく起動失敗したため、設定済みcontroller-venvで検証した。

Claude Sonnet 5の独立した限定レビューを実施（同フォルダclaude_review.json）。
GETも同じポートへ限定する提案は採用しない。別controllerを読み取り専用で監視する既存要件に反するため。
外部OriginはGET/OPTIONSでも403となる追加テストで検証した。静的discoveryのnonceは秘密資格情報の代替ではなく、
POST側のOrigin/Host検査と併用する。ローカル利用者の悪意あるプロセスまで隔離する仕組みではない。
Content-Lengthの非標準表記は拒否される。HTTPの任意payloadを扱わず、固定CLIのみ呼ぶ。
今回の確認範囲では未解決P0/P1なし。これは研究結果の採用承認ではない。

PC再ログオン後のUIサービス起動、実Gurobi計算中の親機故障試験は今回未実施。
全12週の計算完了、メール単独自動送信、全機器無故障をこの変更で保証しない。
通常操作は[運用手順](../guides/weekly_operations.md)を参照。
