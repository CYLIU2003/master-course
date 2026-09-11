# デスクトップで旧結果の非有限値を表示する

## 問題と変更範囲

実parent `771d115b-75b0-49f7-a7f0-25f259a2cd21` のSQLite結果には、Python JSONが出力した裸 `Infinity` が残っていた。新しいstream projectionのstrict parserは、投影対象外の項目でもこれを拒否し、シナリオ概要を取得できなかった。

`bff/store/desktop_json.py` のreaderはソースを64 KiB以下で読み、引用符・escape・chunk境界を追跡する。値の区切りにある `Infinity` / `-Infinity` / `NaN` だけを引用してからparserへ渡す。文字列内の同名テキスト、日本語、escape、有限値、ゼロ、false、nullを保持し、その他の不正なtokenは拒否される。大量の通常JSONにはchunk単位のquote parityによる経路を使う。要約の10,000イベント制限とキャッシュ境界は維持する。

これは表示専用の変換であり、SQLite・JSON原本、Prepare、solver、会計、物理検証、研究採用の処理は変更しない。非有限値は文字なので、画面の数値型を要求する最終会計欄は「未確定」となる。進行中の4週診断は `0cc91fa2072e5d72aa43bd4c3ca428ab74ec9b64` の凍結worktreeで続け、その結果を後続UI commitのsolver証拠へ付け替えない。

## 検証

- 関連50テストが2.64秒で通過。1〜34 byteの小分け読取り、escape、日本語、非有限値3種、null/zero/false、不正token、HTTP JSON化、SQLite blob、原本SHA-256不変、大量の未投影配列を確認した。
- 実parentの概要をPydantic契約で検証し、JSON化に成功した（0.816秒、15,717 bytes）。
- Windows portable版をMAINで17:03 JSTに再起動し、認証付きBFF・一覧・概要・時刻表のsmokeが成功した。終了後、起動したElectron/BFFの残留を認めなかった。画像は `output/desktop-smoke/`、前のsmokeは `output/desktop_delivery_20260911/baseline_162002/` にhash照合して保管した。
- 全体回帰は `python -X utf8 -m pytest -q` で **2,093 passed / 2 failed、89.43秒**。残る失敗は既存のPowerPoint証拠ハッシュと部品同一性の2件で、原本は変更していない。記録は `output/pytest_desktop_legacy_json_20260911.log`。
- GPT-5.6 Lunaがreader・fast path・projection wrapper・対応テストを独立レビューし、P0/P1指摘0件。読取りコードとテストが対象で、LunaによるElectron実画面操作や研究モデル全体の採用レビューは含まない。

100万行の合成データを新たに構築して再測定した。

| 読取り | 時間 | Python最大割当 |
|---|---:|---:|
| SQLite時刻表の末尾250件 | 1.2044秒 | 2,043,874 bytes |
| Parquetの末尾250件 | 0.00823秒 | 84,144 bytes |
| 36,000,131 bytesの結果投影 | 5.7333秒 | 1,781,618 bytes |
| 結果キャッシュ | 0.000983秒 | 137,775 bytes |

5検査すべて通過。記録は `output/desktop_scalability/synthetic-3fysuzkv/benchmark.json`。途中実装の初回投影14.8808秒は `synthetic-ckidsauh/benchmark.json` に残し、修正後の値と混ぜない。数値は読取り時のPython割当で、SQLite/Arrowのnative allocation、データ構築、solverは測定に含まない。
