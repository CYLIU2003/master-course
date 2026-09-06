# ParamEditor 実装指示書（エージェント向け）

## 概要

`ParamEditor.tsx` をプロジェクトの既存フロントエンドに統合する。
モックアップの思想を全部適用するのではなく、**性能と実装コストを優先**して
必要な部分だけ取り込む方針。

---

## 前提確認タスク（実装前に必ず行うこと）

1. **既存の型定義を確認する**
   - `BusParams` インターフェースは仮定義。既存の API スキーマ（`/api/v1/optimize` のリクエスト型）と
     フィールド名・型を一致させること。
   - `charge_hours: number[]` は API が `string`（例: `"22:00-06:00"`）を期待している場合は変換層を挟む。

2. **スタイリング方式を確認する**
   - 現在プロジェクトが Tailwind を使っているなら inline style をすべて Tailwind クラスに置き換える。
   - CSS Modules の場合は `ParamEditor.module.css` を別途作成する。
   - `var(--color-*)` / `var(--border-radius-*)` は claude.ai 専用変数なので、
     プロジェクト側の CSS 変数またはデザイントークンに読み替えること。

3. **既存フォーム管理ライブラリを確認する**
   - `react-hook-form` または `formik` が入っているなら、
     コンポーネント内の `useState` を `useForm` の `register` / `setValue` に置き換える。
   - バリデーション（`zod` / `yup`）がある場合は `BusParams` の schema を定義して接続する。

---

## 各サブコンポーネントの実装方針

### SliderField（スライダー + 数値欄の連動）

**現状**: `useDeferredValue` でスライダー操作中の再レンダーを後回しにしている。

**判断ポイント**:
- 親コンポーネントが軽い（API 呼び出しなし、計算なし）なら `useDeferredValue` は削除してよい。
- 親側でリアルタイムにプレビュー計算を走らせるなら必要。スラーダー onInput で debounce(300ms) を
  入れる選択肢もある（`lodash.debounce` or `use-debounce`）。

**注意点**:
- `number` input は `value` が空文字になるケースを処理する。
  現状 `parseInt(e.target.value) || min` で min に丸めているが、
  ユーザーが途中入力（"1" を消して "1" → "" → "15" と打つ）を邪魔しないよう
  `onBlur` でクランプする実装も検討する。

### FleetVisualizer（車両構成ビジュアル）

**現状**: 台数分の `<span>` を生成。`MAX_ICONS = 40` 以上はテキストで省略。

**性能上の注意**:
- 台数が多い場合（50台超）は DOM が増えるので、`MAX_ICONS` を引数化して
  呼び出し元で制御できるようにすること。
- アニメーションは今回実装していない。追加する場合は CSS transition のみ（JS アニメーションは不要）。
- `React.memo` で包むと BEV/ICE 以外のパラメータ変更時の再レンダーをスキップできる。

### ChargeWindowSelector（充電時間帯トグル）

**現状**: 24 個の `div` をクリックでトグル。`useMemo` で `Set` を再計算。

**改善余地**:
- 「深夜一括選択」「すべてリセット」ショートカットボタンがあると便利。追加するかどうかは UX 判断。
- `charge_hours` を `boolean[24]` で持つ方が配列生成コストが下がる。
  API が `number[]` を期待する場合は submit 時に変換する。

### SummaryBar（サマリー派生値）

**現状**: `params` を受け取り毎回計算。

**性能**: 計算が `O(1)` なので `useMemo` は不要。重くなったら足す程度でよい。

---

## プリセット定義の更新

```typescript
// PRESETS の値は実際の路線データに合わせて更新すること。
// 目黒営業所の場合は以下のソースを参照:
// - 黒01/黒02/東98/渋71/渋72 の運行本数・距離
// - 営業所の充電設備台数・出力
// - 実績電力契約（TOU プランの種類）
```

具体的な数値は `master-course` リポジトリの `data/routes/meguro.json`（または相当ファイル）から取得する。

---

## 使用例

```tsx
// ウィザードの Step 2 で呼び出す場合
import ParamEditor, { BusParams } from "./ParamEditor";

const [params, setParams] = useState<BusParams | null>(null);

<ParamEditor
  initialParams={selectedCaseDefaults}   // Step 1 で選んだ Case のデフォルト値
  onChange={(p) => setParams(p)}         // リアルタイム反映（不要なら省略）
  onSubmit={(p) => startOptimization(p)} // Step 3 への遷移
/>
```

---

## 実装しないもの（意図的な省略）

| 要素 | 省略理由 |
|------|----------|
| TOU badge の色分け | 視覚効果は小さく、メンテコスト↑。グレー統一でよい |
| プリセット保存（ローカルストレージ） | スコープ外。必要なら別 issue で |
| レスポンシブ（スマホ対応） | 業務ツールは PC 前提のため優先度低 |
| アニメーション・トランジション | CSS transition のみ（JS 不要） |
| エラートースト | 既存の通知システムに統合すること |
