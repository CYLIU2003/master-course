---
name: mit-programming-style
description: MIT最高水準のプログラミングスタイル・設計思想・コーディング規約を適用するスキル。コードを書く、実装する、設計する、アーキテクチャを考える、クリーンコード、リファクタリング、関数設計、クラス設計、API設計などが必要な場面では必ずこのスキルを参照すること。「実装して」「書いて」「設計して」「コードを作成して」などのキーワードでも積極的にトリガーすること。
---

# MIT-Style Programming Skill

MITで培われた、世界最高水準のエンジニアリング哲学とコーディング規範。

---

## 0. 根本原則

```
Correctness → Clarity → Efficiency （この順番で優先）
```

> "Make it work, make it right, make it fast." — Kent Beck

正しく動くことが最優先。次に読める・保守できること。最後に速くする。
早すぎる最適化は万悪の根源 (Knuth)。

---

## 1. 命名規則（Naming Convention）

### 原則: 名前は意図を語る
```python
# ❌ Bad
def calc(x, y, z):
    return x * y - z

# ✅ Good
def compute_net_revenue(gross_sales: float, tax_rate: float, returns: float) -> float:
    return gross_sales * (1 - tax_rate) - returns
```

### 命名の7つのルール
1. **発音できる名前**を使う（`genymdhms` → `generationTimestamp`）
2. **検索できる名前**を使う（マジックナンバー禁止）
3. **エンコーディングを避ける**（ハンガリアン記法禁止：`strName` → `name`）
4. **文脈を活用**する（クラス `User` 内なら `name` で十分）
5. **bool変数は is/has/can/should で始める**（`isValid`, `hasPermission`）
6. **関数は動詞**から始める（`get`, `set`, `compute`, `validate`, `render`）
7. **略語は最小限**（`usr` → `user`, `btn` → `button`）

---

## 2. 関数設計（Function Design）

### 単一責任の原則（SRP）
```python
# ❌ 複数の責任を持つ関数
def process_user(user_data):
    # DBに保存
    db.save(user_data)
    # メール送信
    send_email(user_data['email'])
    # ログ出力
    print(f"User {user_data['id']} processed")

# ✅ 責任を分離
def save_user(user_data: dict) -> User:
    return db.save(user_data)

def notify_user_registration(email: str) -> None:
    send_email(email, template="welcome")

def log_user_creation(user_id: str) -> None:
    logger.info(f"User created: {user_id}")
```

### 関数の長さ
- **理想: 5〜20行**
- 画面1ページに収まる長さ
- インデントが深くなったら（3段以上）、分割のサイン

### 引数の数
```
0個: 理想
1個: 良い (単項関数)
2個: 許容 (二項関数)
3個: 要検討
4個以上: データクラス/辞書でラップを検討
```

### 副作用をゼロに近づける（Pure Functions優先）
```python
# ❌ 副作用あり（グローバル状態を変更）
total = 0
def add_to_total(x):
    global total
    total += x

# ✅ 純粋関数
def compute_total(values: list[float]) -> float:
    return sum(values)
```

---

## 3. エラーハンドリング

### 原則: エラーを隠蔽するな
```python
# ❌ 悪い例：エラーを飲み込む
try:
    result = risky_operation()
except Exception:
    pass  # 絶対にやってはいけない

# ✅ 良い例：具体的な例外をキャッチし、ログを残す
try:
    result = risky_operation()
except FileNotFoundError as e:
    logger.error(f"Config file missing: {e}")
    raise ConfigurationError("System configuration is incomplete") from e
except PermissionError as e:
    logger.error(f"Insufficient permissions: {e}")
    raise
```

### カスタム例外クラスの設計
```python
class AppError(Exception):
    """アプリケーション基底例外"""
    def __init__(self, message: str, error_code: str, context: dict = None):
        super().__init__(message)
        self.error_code = error_code
        self.context = context or {}

class ValidationError(AppError):
    """入力バリデーションエラー"""

class NotFoundError(AppError):
    """リソース未発見エラー"""
```

---

## 4. コメントの書き方

### コメントは「なぜ」を書く（「何を」はコードが語る）
```python
# ❌ Bad: コードの再説明
# ユーザーのリストをソートする
users.sort(key=lambda u: u.created_at)

# ✅ Good: 意図・制約・理由を書く
# 最新登録順にソート（UI仕様: 新規ユーザーを上部に表示する要件 #1234）
users.sort(key=lambda u: u.created_at, reverse=True)
```

### Docstring（関数レベルドキュメント）— Google Style
```python
def compute_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """2つのベクトル間のコサイン類似度を計算する。

    Args:
        vec_a: 第1ベクトル。ゼロベクトルは不可。shape: (n,)
        vec_b: 第2ベクトル。ゼロベクトルは不可。shape: (n,)

    Returns:
        コサイン類似度。範囲: [-1.0, 1.0]

    Raises:
        ValueError: どちらかのベクトルがゼロの場合。
        ValueError: ベクトルの次元数が一致しない場合。

    Example:
        >>> compute_similarity(np.array([1, 0]), np.array([1, 0]))
        1.0
        >>> compute_similarity(np.array([1, 0]), np.array([0, 1]))
        0.0
    """
```

---

## 5. 設計パターンの適用基準

| 状況 | 推奨パターン |
|------|-------------|
| オブジェクト生成が複雑 | Factory / Builder |
| 同一インスタンスを共有したい | Singleton（慎重に） |
| アルゴリズムを切り替えたい | Strategy |
| 状態遷移がある | State Machine |
| イベント通知が必要 | Observer / Pub-Sub |
| 外部APIをラップしたい | Adapter / Facade |
| 処理をパイプライン化したい | Pipeline / Chain of Responsibility |

**パターン適用の鉄則: 問題が先、パターンは後。パターンのために問題を作るな。**

---

## 6. コード構造のテンプレート

### Pythonモジュールの標準構造
```
module_name/
├── __init__.py          # 公開API定義
├── models.py            # データモデル（副作用なし）
├── services.py          # ビジネスロジック
├── repositories.py      # データアクセス層
├── exceptions.py        # カスタム例外
├── validators.py        # バリデーション
└── tests/
    ├── test_models.py
    ├── test_services.py
    └── fixtures.py
```

### クラス設計のテンプレート
```python
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class Entity:
    """エンティティの説明。

    Attributes:
        id: 一意識別子
        name: 表示名
    """
    id: str
    name: str
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self._validate()

    def _validate(self) -> None:
        if not self.id:
            raise ValueError("id cannot be empty")
        if not self.name:
            raise ValueError("name cannot be empty")

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, data: dict) -> "Entity":
        return cls(id=data["id"], name=data["name"], metadata=data.get("metadata", {}))
```

---

## 7. テスト設計の原則（FIRST原則）

```
Fast       — テストは高速であること（< 1秒/テスト）
Isolated   — テストは独立していること（実行順序に依存しない）
Repeatable — 何度実行しても同じ結果
Self-validating — パス/フェイルが自明
Timely     — プロダクションコードと同時に書く（TDD推奨）
```

### テストの書き方（AAA パターン）
```python
def test_compute_net_revenue_with_returns():
    # Arrange（準備）
    gross_sales = 1000.0
    tax_rate = 0.1
    returns = 50.0

    # Act（実行）
    result = compute_net_revenue(gross_sales, tax_rate, returns)

    # Assert（検証）
    assert result == pytest.approx(850.0)
```

---

## 8. バージョン管理とコミットメッセージ

### Conventional Commits 形式
```
<type>(<scope>): <subject>

<body>（任意）

<footer>（任意: BREAKING CHANGE, Closes #issue）
```

**type の種類:**
- `feat`: 新機能
- `fix`: バグ修正
- `refactor`: 機能変更なしのリファクタリング
- `perf`: パフォーマンス改善
- `test`: テスト追加・修正
- `docs`: ドキュメントのみの変更
- `chore`: ビルドプロセス・補助ツールの変更

**実例:**
```
feat(auth): JWT refreshトークンの自動更新を実装

アクセストークンの有効期限切れを検知し、
refreshトークンを使って自動的に再取得する。

Closes #456
BREAKING CHANGE: AuthClientのコンストラクタにrefreshUrlが必須になった
```
