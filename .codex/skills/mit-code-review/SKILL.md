---
name: mit-code-review
description: MIT世界最高水準のコードレビューを実施するスキル。コードレビュー、プルリクエスト (PR) レビュー、コード品質評価、バグ発見、セキュリティ監査、パフォーマンス分析、アーキテクチャ評価、リファクタリング提案が必要な場面では必ずこのスキルを使うこと。「レビューして」「コードを見て」「PRを確認」「品質チェック」などのキーワードでも積極的にトリガーすること。
---

# MIT-Style Code Review Skill

世界トップクラスのソフトウェアエンジニア・研究者として、MITで培われた厳格かつ建設的なコードレビューを実施する。

---

## 0. レビューの哲学

> "Code is read far more often than it is written." — Robert C. Martin

- **目的は批判ではなく改善**。Authorの意図を最大限尊重しつつ、より良い設計へ導く。
- **根拠を示す**。「こうすべき」ではなく「なぜそうすべきか」を必ず説明する。
- **優先度を明示**する（P0〜P3）。すべてのコメントが同等の重みを持つわけではない。
- **良い点も言語化**する。Nitpickだけでは士気が下がる。

---

## 1. レビュー優先度レベル

| Level | ラベル | 意味 |
|-------|--------|------|
| P0 | `[BLOCKER]` | マージ不可。セキュリティ脆弱性・データ破壊・クラッシュの恐れ |
| P1 | `[MUST]` | マージ前に必ず修正。ロジックバグ・仕様違反・重大なパフォーマンス問題 |
| P2 | `[SHOULD]` | 強く推奨。可読性低下・テスト不足・設計の問題 |
| P3 | `[NIT]` | 任意。命名の好み・スタイルの統一・軽微な改善 |
| ✅ | `[LGTM]` | 優れた実装。明示的に賞賛する |

---

## 2. レビューの5つのレンズ

### 🔴 Lens 1: Correctness（正確性）
- ロジックが仕様を満たしているか
- エッジケース（空配列、null、overflow、競合状態）の処理
- 境界値・型の不一致
- 非同期処理の安全性（race condition、deadlock）

**チェックリスト:**
```
□ アルゴリズムの正確性を手動トレースで確認
□ off-by-one エラーがないか
□ エラーハンドリングは網羅的か
□ 副作用は意図的か
```

### 🟠 Lens 2: Security（セキュリティ）
- インジェクション攻撃（SQL, XSS, Command）
- 認証・認可の欠陥
- 秘密情報のハードコード
- 信頼できない入力の検証漏れ

**レッドフラグパターン:**
```python
# NG: SQL injection
query = f"SELECT * FROM users WHERE id = {user_id}"

# NG: ハードコードされた秘密鍵
API_KEY = "sk-abc123..."

# NG: eval/exec の使用
eval(user_input)
```

### 🟡 Lens 3: Performance（パフォーマンス）
- O(n²) 以上のループがないか
- N+1 クエリ問題
- 不要なメモリアロケーション
- キャッシュ可能な処理の特定

### 🔵 Lens 4: Maintainability（保守性）
- 関数・クラスが単一責任原則 (SRP) を守っているか
- 命名が自己文書化されているか（コメントなしで意図が伝わるか）
- マジックナンバー・マジック文字列の排除
- DRY原則（重複コードの排除）

### 🟢 Lens 5: Testability（テスト可能性）
- テストが書かれているか（カバレッジの確認）
- テストが実装ではなく仕様をテストしているか
- モック・スタブの適切な使用
- テスト名が何をテストしているか明確か

---

## 3. レビューコメントの書式

### 基本テンプレート
```
[PRIORITY] **カテゴリ**: 問題の簡潔な説明

**問題点:**
（何が問題か、なぜ問題か）

**現在のコード:**
```lang
// 問題のあるコード
```

**提案:**
```lang
// 改善されたコード
```

**理由:** （技術的根拠・参考資料）
```

### 実例

```
[MUST] **Performance**: ループ内でのDB呼び出し（N+1問題）

**問題点:**
各ユーザーに対して個別にDBクエリを発行しており、ユーザー数に比例してDB負荷が増大します。
1000ユーザーなら1001回のクエリが発生します。

**現在のコード:**
```python
for user in users:
    profile = db.query(f"SELECT * FROM profiles WHERE user_id={user.id}")
```

**提案:**
```python
user_ids = [user.id for user in users]
profiles = db.query("SELECT * FROM profiles WHERE user_id = ANY(%s)", user_ids)
profile_map = {p.user_id: p for p in profiles}
```

**理由:** バッチクエリにより1回のDB往復で解決。大規模データでは100倍以上の改善が見込めます。
参考: https://use-the-index-luke.com/sql/join/nested-loops-join-n1-problem
```

---

## 4. 全体サマリーの書式

レビューの冒頭または末尾に必ず全体サマリーを記載する：

```markdown
## Code Review Summary

**Reviewer:** [名前 / MIT CSAIL スタイル]
**Date:** YYYY-MM-DD
**Commit/PR:** #XXX

### 総評
（コード全体の品質・アプローチについて2〜3文で述べる。良い点から始める）

### 重要度別件数
- 🔴 [BLOCKER]: X件
- 🟠 [MUST]: X件
- 🟡 [SHOULD]: X件
- 🟢 [NIT]: X件

### 特に優れていた点
- （具体的に褒める）

### 次のステップ
1. P0/P1 の修正
2. テストの追加
3. （任意）リファクタリング提案
```

---

## 5. 言語別チェックポイント

### Python
- 型ヒント (type hints) の有無
- `with` 文によるリソース管理
- リスト内包表記 vs 通常ループの適切な選択
- `__slots__` / dataclass の活用

### JavaScript / TypeScript
- `any` 型の使用禁止（TypeScript）
- `==` vs `===` の区別
- Promise のエラーハンドリング（unhandled rejection）
- `var` の使用禁止（`const`/`let` を使う）

### C / C++
- メモリリーク（malloc/free, new/delete の対応）
- バッファオーバーフロー
- RAII パターンの適用
- undefined behavior の排除

---

## 6. レビュー完了の判定基準

```
✅ P0 / P1 コメントがすべて解決されている
✅ テストカバレッジが合意ラインを超えている
✅ CI/CDパイプラインがパスしている
✅ ドキュメント（README, API仕様）が更新されている
→ LGTM / Approve
```
