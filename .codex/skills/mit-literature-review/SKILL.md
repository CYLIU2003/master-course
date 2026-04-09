---
name: mit-literature-review
description: MIT・トップジャーナル水準の先行文献調査・引用・参考文献管理を実施するスキル。文献調査、サーベイ論文執筆、Related Workの記述、引用の書式、参考文献リストの作成、先行研究との差分分析が必要な場面では必ずこのスキルを使うこと。「文献を調べて」「先行研究は？」「Related Workを書いて」「引用して」「参考文献をまとめて」などのキーワードでも積極的にトリガーすること。
---

# MIT-Style Literature Review Skill

系統的文献調査（Systematic Literature Review）とトップジャーナル品質のRelated Work記述。

---

## 0. 文献調査の哲学

> "If I have seen further, it is by standing on the shoulders of giants." — Isaac Newton

先行研究は「超えるべき壁」ではなく「土台」。徹底的に理解してこそ、本当の貢献が生まれる。

- **網羅性**: 重要な先行研究を見逃さない
- **批判的読解**: 手法・結果・限界を冷静に評価する
- **合成**: 個別論文をつなぎ、分野の全体像を描く
- **正確な引用**: 著者の意図を歪めない

---

## 1. 文献調査プロセス（PRISMA準拠）

```
Phase 1: Identification（収集）
  → 複数のDBで網羅的に検索
  → 参考文献の芋づる式調査（Backward/Forward citation）

Phase 2: Screening（一次選別）
  → タイトル・アブストラクトを読む
  → 選定基準 (Inclusion/Exclusion) を適用

Phase 3: Eligibility（二次選別）
  → 全文を読む
  → 品質評価

Phase 4: Inclusion（最終選定）
  → データ抽出
  → 合成・整理
```

---

## 2. 主要データベースと検索戦略

### 推奨データベース（分野別）
| 分野 | 主要DB |
|------|--------|
| CS / AI / ML | ACM DL, IEEE Xplore, arXiv, DBLP, Semantic Scholar |
| 自然科学 | PubMed, Web of Science, Scopus |
| 工学 | IEEE Xplore, ASCE, ASME |
| 経済・社会 | SSRN, JSTOR, EconLit |
| 総合 | Google Scholar（補完用）|

### 効果的な検索クエリの構築
```
ブーリアン演算子:
  AND — 両方を含む（絞り込み）
  OR  — いずれかを含む（拡張）
  NOT — 除外

例（ML×医療診断）:
("deep learning" OR "neural network" OR "transformer")
AND ("medical diagnosis" OR "clinical decision support")
AND ("chest X-ray" OR "CT scan")
NOT "review"

フィールド指定:
  title:, abstract:, keyword:
  年範囲: 2019..2024
```

### 検索の記録（再現性のため）
```markdown
### 検索記録
- **DB**: ACM Digital Library
- **クエリ**: ("code generation" AND "large language model") NOT "survey"
- **実施日**: 2024-01-15
- **フィルタ**: 2020年以降、査読あり
- **ヒット数**: 347件
- **選定数**: 42件（除外理由を記録）
```

---

## 3. 論文の批判的評価フレームワーク

### 論文1本を読む順番
```
1. タイトル + アブストラクト（2分）→ 読む価値があるか判断
2. Introduction の最後（貢献リスト）（3分）→ 主張を把握
3. Figures & Tables（5分）→ 結果を把握
4. Methodology（10-20分）→ 手法を理解
5. Conclusion + Limitations（5分）→ 著者自身の評価
6. Related Work（5分）→ 文脈を理解
7. 全文精読（30-60分）→ 詳細な理解
```

### 批判的評価の5軸（5C Framework）
```
Contribution  — 何が新しいか？既存研究との差は何か？
Correctness   — 実験は正しく設計されているか？統計は妥当か？
Clarity       — 手法は再現可能なほど明確に書かれているか？
Completeness  — 比較すべき先行研究を網羅しているか？
Credibility   — 著者・会場・引用数は信頼できるか？
```

### 評価メモのテンプレート
```markdown
## 論文評価メモ

**タイトル**: XXX
**著者**: Doe et al. (2023)
**会場**: NeurIPS 2023
**引用数**: 142

### 主要貢献
- ...

### 手法の核心
- ...

### 強み
- ...

### 弱み・限界
- ...

### 自分の研究との関連
- 自分の研究との差分: ...
- 使える手法・アイデア: ...
- 反論・批判できる点: ...
```

---

## 4. Related Work の書き方

### 構成パターン

**パターンA: テーマ別分類（最も一般的）**
```
2. Related Work

2.1 Large Language Models for Code
（コード生成系の先行研究をまとめる）

2.2 Repository-Level Code Analysis
（リポジトリ全体を扱う研究）

2.3 Graph Neural Networks for Program Understanding
（GNNの応用）
```

**パターンB: 時系列（発展の流れを示す場合）**
```
2. Background and Related Work
（LSTM時代→Attention→Transformer→LLMと発展を追う）
```

### Related Work の文章パターン

**グルーピング + 比較:**
```
Several approaches have addressed code summarization using
sequence-to-sequence models [1, 2, 3]. While these methods
achieve competitive results on single-function tasks,
they fail to capture cross-file dependencies—a limitation
our work directly addresses.
```

**認めつつ差別化:**
```
Most related to our work is CodeBERT [4], which pre-trains
a transformer on unimodal and bimodal data. Unlike CodeBERT,
which operates at the function level, RepoFormer explicitly
models repository-level dependency graphs, enabling it to
handle multi-file synthesis tasks (Section 4.3).
```

**先行研究の分類表:**
```markdown
| 手法 | 入力粒度 | グラフ使用 | 多言語 | ベンチマーク |
|------|---------|-----------|--------|-------------|
| Codex [5] | 関数 | ✗ | ✓ | HumanEval |
| AlphaCode [6] | 問題文 | ✗ | ✓ | CodeContests |
| **RepoFormer（本研究）** | **リポジトリ** | **✓** | **✓** | **HumanEval+, MBPP+** |
```

---

## 5. 引用の書式

### IEEE スタイル（CS系標準）
```
参照番号形式: [1], [2, 3], [4]–[7]

参考文献リスト例:
[1] J. Doe, A. Smith, and B. Lee, "RepoFormer: Repository-level
    code generation via graph transformers," in Proc. NeurIPS,
    2023, pp. 1234–1245.

[2] OpenAI, "GPT-4 technical report," arXiv:2303.08774, 2023.
    [Online]. Available: https://arxiv.org/abs/2303.08774
```

### ACM スタイル
```
参照形式: [Doe et al. 2023] または (Doe et al., 2023)

参考文献リスト:
Doe, J., Smith, A., and Lee, B. 2023. RepoFormer: Repository-level
code generation via graph transformers. In Advances in Neural
Information Processing Systems (NeurIPS).
```

### APA スタイル（一部CS系・工学系）
```
本文中: (Doe et al., 2023)

参考文献:
Doe, J., Smith, A., & Lee, B. (2023). RepoFormer: Repository-level
code generation via graph transformers. Advances in Neural
Information Processing Systems, 36, 1234–1245.
```

### arXiv 論文の引用
```
Doe, J., Smith, A., & Lee, B. (2023). RepoFormer: Repository-level
code generation via graph transformers. arXiv preprint arXiv:2301.XXXXX.
```

---

## 6. 引用のルールと倫理

### やってはいけないこと
```
❌ 孫引き: 読んでいない論文を引用する
❌ 引用歪曲: 著者の主張と逆の文脈で引用する
❌ 自己引用の過剰: 無関係な自分の論文を水増しする
❌ 権威引用: 有名人の名前を箔付けに使う（内容で引用する）
❌ 肯定的引用のみ: 自分に不都合な先行研究を隠す
```

### 引用の判断基準
```
引用すべき場合:
✅ 具体的な事実・数値・主張の出典
✅ 使用した手法・アルゴリズムの原典
✅ 使用したデータセットの原典
✅ 反論・批判する先行研究
✅ 定義・用語の初出

引用不要の場合:
⬜ 一般常識・自明な事実
⬜ 自分のオリジナルの考え・観察
```

---

## 7. 文献管理ツール

| ツール | 特徴 | 推奨ユーザー |
|--------|------|-------------|
| **Zotero** | 無料・オープン・ブラウザ連携 | 一般研究者 |
| **Mendeley** | Elsevier系・PDF管理が強い | 工学・医学 |
| **Paperpile** | Google Drive連携・クリーンUI | Google Docs利用者 |
| **BibTeX + Overleaf** | LaTeX統合・CS系標準 | CS研究者 |
| **Obsidian + Zotero** | Zettelkasten式知識管理 | 長期研究者 |

### BibTeX エントリの標準形式
```bibtex
@inproceedings{doe2023repoformer,
  title     = {RepoFormer: Repository-Level Code Generation
               via Graph Transformers},
  author    = {Doe, John and Smith, Alice and Lee, Bob},
  booktitle = {Advances in Neural Information Processing Systems},
  volume    = {36},
  pages     = {1234--1245},
  year      = {2023},
  url       = {https://arxiv.org/abs/2301.XXXXX}
}

@article{vaswani2017attention,
  title   = {Attention is All You Need},
  author  = {Vaswani, Ashish and others},
  journal = {Advances in Neural Information Processing Systems},
  volume  = {30},
  year    = {2017}
}
```

---

## 8. サーベイ論文の構成テンプレート

```markdown
# [分野名]に関するサーベイ: [サブテーマ]

## Abstract

## 1. Introduction
   1.1 背景と動機
   1.2 スコープと定義
   1.3 既存サーベイとの違い
   1.4 本稿の構成

## 2. 分類体系（Taxonomy）
   （図: 分野全体のマインドマップ or ツリー図）

## 3. カテゴリ別詳細
   3.1 カテゴリA
   3.2 カテゴリB
   ...

## 4. ベンチマーク・データセット一覧

## 5. 比較表（手法 × 評価指標）

## 6. 未解決課題と今後の展望

## 7. 結論

## References
```
