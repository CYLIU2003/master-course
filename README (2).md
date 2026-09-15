# ７日間・季節別日射量 拡張準備パッケージ

**最初に `調査結果と拡張仕様書.md` を読む。既存モデルへの作業は `実装エージェント指示書.md` を使う。**

このパッケージは、限定的な暦修正パッチ、Solcast年間取得用の補助スクリプト、季節×天候の集計試作、33件の局所テストを含む。完成した７日間最適化システムや、取得済みの年間Solcastデータではない。

## 内容

| ファイル | 役割 |
|---|---|
| `調査結果と拡張仕様書.md` | 調査で確認した不具合、必要な研究設計とシステム変更 |
| `実装エージェント指示書.md` | 元リポジトリでの具体的な作業順・完了条件 |
| `patches/0001_calendar_alias_and_unknown_rows.patch` | 暦ID認識・判定不能行の見逃しに対する限定パッチ |
| `tools/calendar_patch.py` | 元のGit blobを検査して差分のみ生成するツール |
| `tools/solcast_year.py` | 月分割の年間取得計画。通常は通信しないdry-run |
| `tools/seasonal_curves.py` | 取得済み原本と天候ラベルから12区分を集計する試作 |
| `evidence/` | 元暦ソース、再現結果、pytestログ、差分適用検査 |
| `acquisition_plan_*/` | 実行済みdry-run。実データではない |
| `tsurumaki_site.json` | 既存座標。傾斜・方位は未確認のためnull |
| `weather_labels_template.csv` | 出典付き天候ラベルの入力書式。空のテンプレート |
| `seasonal_curve_readiness.json` | 全12区分が未作成であることを示す管理情報 |
| `sources.json` / `DELIVERY_STATUS.json` | 出典と、実施済み／未実施の機械可読記録 |

## 実行環境とテスト

コードはPython標準ライブラリを使用する。テストのみpytestが必要。この環境ではPython 3.13、pytest 9.0.2で確認した。他のPython版とWindows上での動作は未検証である。

パッケージのフォルダーで次を実行する。

```powershell
python -m pytest -q tests
```

今回の結果は33 passed。元リポジトリ全体の回帰試験ではない。気象のテスト入力は人工データで、弦巻の実績としては使用しない。

## 暦パッチ：元リポジトリでまず差分を確認する

対象は `CYLIU2003/master-course` のコミット `5fac09d9a5775192ab8d3e507c5e72a6fd36afe2` にある `src/optimization/common/service_calendar.py`。元ファイルのGit blobは `65445c15882b11301c7c552c0fd56c1395fe2ab4`。

パッケージを元リポジトリの外に展開し、元リポジトリのPowerShellで `$package` をその実在する展開先に設定する。既存変更を上書き・破棄しない。

```powershell
# $package はこのパッケージを展開したフォルダーへのパスとする。
git status --short
git rev-parse HEAD
git apply --check "$package\patches\0001_calendar_alias_and_unknown_rows.patch"
```

差分を読み、現在の元コードとの一致を確認してから、作業ブランチ上で適用する。エラー時に `--reject` 等で無理に押し込まない。SOCの制約、土休日の元時刻表、複数日組立てはこのパッチの対象外である。

```powershell
git apply "$package\patches\0001_calendar_alias_and_unknown_rows.patch"
```

適用後は元リポジトリ内の関連テスト・全体テストが必要。配布パッケージの33件だけで研究実行可能と判定しない。

## Solcast：まず取得計画だけを作る

パッケージ内で実行する。次のコマンドはAPIへ接続しない。

```powershell
python tools/solcast_year.py --site tsurumaki_site.json --start 2025-01-01 --end-exclusive 2026-01-01 --minutes 15 --out acquisition_plan_cy2025
```

2025年度も含む原本範囲の計画は次のとおり。

```powershell
python tools/solcast_year.py --site tsurumaki_site.json --start 2025-01-01 --end-exclusive 2026-04-01 --minutes 15 --out acquisition_plan_union
```

2025年度だけなら開始を2025-04-01、終端を2026-04-01にする。終端は区間に含まない。

**認証付きのダウンロード処理は今回未試験である。** SolcastアカウントでHistoric APIの権限、15分データの利用可否、残り取得枠、課金の可能性を確認する。APIキーは環境変数 `SOLCAST_API_KEY` に安全に設定し、ソース・JSON・Git・チャットへ書かない。

最初は１か月だけを別ディレクトリで取得し、返却フィールドと期待区間を確認する。実行時は、上のコマンドへ `--execute --acknowledge-quota` を追加する。この２オプションが揃わなければ実取得しない。HTTPエラーや欠損時に自動で別データへ切り替えることはしない。

傾斜・方位がnullの状態ではGHI中心の取得となる。GTIが必要な場合は、既存PV設備の設定とSolcastの角度定義を照合したうえでsiteファイルを確定する。実際にはGHIのみを保存するわけではなく、DNI/DHIや気象等も要求する。

## 12区分集計：年間原本とラベルが揃ってから

`weather_labels_template.csv` の書式に合わせ、対象期間の全日についてラベルと出典を整備する。`weather_class` は `sunny` / `cloudy` / `rainy`、`quality_flag` は確認済み行のみ `accepted`。日射量の小ささだけを理由にrainyへ分類してはいけない。

Solcast取得スクリプトが生成した原本JSONとmanifestのディレクトリを指定する。次は未取得データを前提にした利用手順であり、今回の実行済み結果ではない。

```powershell
python tools/seasonal_curves.py --raw-dir solcast_acquisition --weather-labels weather_labels_2025.csv --start 2025-01-01 --end-exclusive 2026-01-01 --minutes 15 --field ghi --min-days 10 --output seasonal_curves_2025.json
```

GTIを実際に取得した場合に限り `--field both` が使える。最低10日は暫定の品質管理値で、統計的十分性の証明ではない。欠損・未確認ラベル・標本不足があれば停止する。`--diagnostic` は研究採用を保証しない不完全な診断出力に限る。

このツールは日射量の平均・分位点等を集計する前処理試作である。PV発電への変換、予報の学習・誤差推定、実際の最適化入力への接続は別途実装する。

## 変更・取得・実行していないもの

GitHubのmain、CI、元の研究結果は変更していない。agent-browserでの全便照合、2025年の新規日射量取得、実績由来の12曲線、SOC最適化制約修正、７日間solve、全体回帰試験は未実施。
