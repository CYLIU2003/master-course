# EV Bus Dispatch Planning System (Master Course)

このリポジトリは、修士研究向けの **EVバス配車・充電計画・運行最適化** プロジェクトです。  
現在の `main` は、**新フロント思想（React + FastAPI BFF + Pythonコア）** を前提とした構成です。

---

## 1. まず最初に: ブランチ方針

### `main`（現行）

- 採用アーキテクチャ: **frontend-first + API-driven**
- UI: `frontend/`（React + TypeScript）
- Backend for Frontend: `bff/`（FastAPI）
- 研究ロジック: `src/`（dispatch / pipeline / optimizer / simulator）

### `old`（凍結）

- 旧 Streamlit UI 系資産を保持する退避ブランチ
- 参照用、基本的に今後は更新しない

> つまり、今後の機能追加・改修は `main` 上で `frontend/` と `bff/` を中心に進めます。

---

## 2. 設計思想（新フロント思想）

### 2.1 Frontendのドメイン設計

- 中心概念は `Depot`（営業所）
- `Vehicle` は必ず1つの `depotId` に所属
- `Route` は独立エンティティ
- 権限制御は2層
  - `DepotRoutePermission`
  - `VehicleRoutePermission`

### 2.2 UI構成

- 主タブは2つ
  1. `Planning`（営業所・車両・路線のマスタ管理）
  2. `Simulation`（シミュレーション環境設定）
- その下に `Dispatch` / `Results` を常設

### 2.3 バックエンド通信方針

- Frontendは `/api` だけを叩く
- BFFが Pythonコア（`src/`）を呼び出す
- 重い処理はジョブ化
  - `POST` で `job_id` 発行
  - `GET /api/jobs/{job_id}` で進捗ポーリング

---

## 3. システム全体像

```text
React Frontend (frontend/)
  -> HTTP /api
FastAPI BFF (bff/)
  -> src.dispatch (timetable-first dispatch)
  -> src.pipeline (build_inputs / solve / simulate / report)
  -> src.* (model, constraints, simulator)
```

---

## 4. クイックスタート

### 4.1 前提

- Python 3.11+ 推奨
- Node.js 18+ 推奨
- npm 9+ 推奨

### 4.2 初回セットアップ（1回だけ）

```bash
python -m pip install -r requirements.txt
```

### 4.3 起動（毎回）

#### ターミナル1: BFF

```bash
python -m uvicorn bff.main:app --reload --port 8000
```

- API base: `http://localhost:8000/api`
- Health: `http://localhost:8000/health`

#### ターミナル2: Frontend

```bash
cd frontend
npm install
npm run dev
```

`npm run dev` は `vite --open` なのでブラウザが自動で開きます。

### 4.4 起動後に何が起きるか

- `http://localhost:5173/` にアクセスすると、アプリは `GET /api/scenarios/default` を呼びます
- シナリオが1件以上ある場合: 最新シナリオへ自動遷移
- シナリオが0件の場合: `Default Scenario` を自動作成して自動遷移
- 遷移先は常に操作開始画面: `/scenarios/{scenarioId}/planning`

つまり、**起動したらそのまま操作画面に入れる**運用です。

---

## 5. 開発時の基本コマンド

## 5.1 Pythonテスト

```bash
python -m pytest tests/ -q
```

## 5.2 Frontendビルド確認

```bash
cd frontend
npm run build
```

## 5.3 BFF import確認

```bash
python -c "from bff.main import app; print(len(app.routes))"
```

---

## 6. APIの責務（BFF）

`bff/` は「UIに必要な粒度」でAPIを提供し、研究コア層との間を吸収します。

- Scenario CRUD
- Depot / Vehicle / Route CRUD
- Depot-Route / Vehicle-Route Permission
- Timetable入出力
- Dispatch処理
  - `build-trips`
  - `build-graph`
  - `generate-duties`
  - `duties/validate`
- ジョブ管理
  - `GET /api/jobs/{job_id}`

現時点で暫定（stub）:

- `run-simulation`
- `run-optimization`

---

## 7. Dispatchコアの不変条件（重要）

`src/dispatch/` は **Timetable first, dispatch second** を厳守します。

- 時刻表が唯一の真実
- 配車は時刻表から導出する
- 物理的に不可能な接続を許可しない

接続可否のハード制約:

1. 位置連続性（deadhead ruleが必要）
2. 時刻連続性（turnaround + deadheadを加味して出発時刻以下）
3. 車種制約（allowed vehicle types）

---

## 8. ディレクトリ構成（mainの実態）

```text
master-course/
|- AGENTS.md
|- README.md
|- requirements.txt
|
|- frontend/                     # React 19 + TS + Vite 7
|  |- src/
|  |  |- api/
|  |  |- app/
|  |  |- features/
|  |  |- hooks/
|  |  |- pages/
|  |  |- stores/
|  |  `- types/
|  `- README.md
|
|- bff/                          # FastAPI BFF
|  |- main.py
|  |- routers/
|  |- store/
|  `- mappers/
|
|- src/                          # 研究コア（配車/最適化/シミュレーション）
|  |- dispatch/
|  |- pipeline/
|  |- constraints/
|  |- preprocess/
|  `- schemas/
|
|- tests/                        # Python test suite
|- data/                         # 入力データ
|- config/                       # 実験設定
|- docs/                         # 補助ドキュメント
|- scripts/
`- schema/
```

---

## 9. 追跡しないもの（Gitポリシー）

以下は生成物のため `main` では追跡しません。

- `outputs/`
- `derived/`
- `results/`
- `__pycache__/`, `*.pyc`
- `frontend/node_modules/`, `frontend/dist/`

必要な成果物がある場合は、リリースノートや別アーティファクト保管先を使って管理してください。

---

## 10. 旧Streamlit資産について

- `main` からは削除済み（設計混在を防ぐため）
- 参照が必要な場合は `old` ブランチをチェックアウト

```bash
git checkout old
```

---

## 11. よくあるハマりどころ

### Q1. FrontendでAPIエラーになる

- BFFが起動しているか確認
- `http://localhost:8000/health` が `{"status":"ok"}` を返すか確認

### Q2. ジョブが終わらない

- `GET /api/jobs/{job_id}` の `status` / `error` を確認
- まず `build-trips` -> `build-graph` -> `generate-duties` の順に実行

### Q3. Gurobiを使う最適化を実行したい

- `gurobipy` は別途導入とライセンス設定が必要
- 未導入時は solver関連の一部機能が利用不可

---

## 12. 今後の優先実装

1. BFFの `run-simulation` を `src/pipeline/simulate.py` と本結合
2. BFFの `run-optimization` を solver実装と本結合
3. FrontendのSimulation設定画面を実データ保存に接続
4. フォームバリデーション（Zod）と編集UX改善

---

## 13. Maintainerメモ

- 研究ロジックは `src/` に集約し、UI層に埋め込まない
- BFFは「薄いオーケストレーション + DTO整形」に限定する
- `constant/` は読み取り専用
