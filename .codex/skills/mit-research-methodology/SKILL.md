---
name: mit-research-methodology
description: MIT・トップジャーナル水準の研究手法・実験設計・論文執筆を実施するスキル。研究計画、実験設計、仮説立案、データ収集・分析、論文執筆、アブストラクト作成、研究の限界・考察の記述が必要な場面では必ずこのスキルを使うこと。「研究して」「実験を設計して」「論文を書いて」「仮説を立てて」「分析して」などのキーワードでも積極的にトリガーすること。
---

# MIT-Style Research Methodology Skill

Nature, Science, NeurIPS, ICML, ACM SIGCOMM などトップカンファレンス・ジャーナルが求める研究の作法。

---

## 0. 研究の哲学

> "The purpose of science is not to explain everything, but to explain things we didn't understand before." — Richard Feynman

- **再現可能性 (Reproducibility)** がすべての基本
- **反証可能性 (Falsifiability)** のない仮説は科学ではない（Popper）
- **Occam's Razor**: 同等に説明できるなら、より単純な仮説を選ぶ
- **Null result も価値がある**: 「効果がなかった」も重要な知見

---

## 1. 研究プロセスの全体像

```
1. Problem Formulation（問題定義）
        ↓
2. Literature Review（先行研究調査）
        ↓
3. Hypothesis Formulation（仮説立案）
        ↓
4. Experimental Design（実験設計）
        ↓
5. Data Collection（データ収集）
        ↓
6. Analysis（分析）
        ↓
7. Interpretation（解釈・考察）
        ↓
8. Writing & Peer Review（論文執筆・査読）
```

---

## 2. 問題定義（Problem Formulation）

### Research Question の構成要素
```
Population  — 誰/何について？
Intervention — 何をする/変える？
Comparison  — 何と比較？
Outcome     — 何を測定？
（PICO フレームワーク）
```

**良いResearch Questionの条件:**
- **Specific**: 曖昧さがない
- **Measurable**: 指標が定量化できる
- **Achievable**: 現実的なリソースで達成可能
- **Relevant**: 分野への貢献が明確
- **Time-bound**: 期間が明確

**例:**
```
❌ 悪い: 「深層学習は自然言語処理に有効か？」（広すぎる）

✅ 良い: 「トークン長1000以下のコード要約タスクにおいて、
         GPT-4ベースのfine-tuningは few-shot prompting に対して
         BLEUスコアで有意な改善（p<0.05）をもたらすか？」
```

---

## 3. 仮説の書き方

### 仮説の3要素
```
H₀ (Null Hypothesis)     : 効果がない・差がない
H₁ (Alternative Hypothesis): 効果がある・差がある
α  (Significance Level)   : 通常 0.05（5%の誤検出を許容）
```

**書式テンプレート:**
```
H₀: [介入] は [対照群] と比較して、[指標] に有意な差を生じさせない
H₁: [介入] は [対照群] と比較して、[指標] を [方向] に有意に [変化] させる

例:
H₀: Transformerベースの要約モデルは、LSTMベースと比較して
    BLEUスコアに統計的有意差を生じない (α=0.05)
H₁: Transformerベースの要約モデルは、LSTMベースと比較して
    BLEUスコアを有意に向上させる
```

---

## 4. 実験設計

### 4.1 変数の定義
| 変数の種類 | 定義 | 例 |
|-----------|------|-----|
| 独立変数 (IV) | 操作・変化させる変数 | モデルアーキテクチャ |
| 従属変数 (DV) | 測定する変数 | BLEU, F1, Accuracy |
| 制御変数 | 一定に保つ変数 | データセットサイズ、GPU種別 |
| 交絡変数 | 統制が難しい影響因子 | データの質のばらつき |

### 4.2 実験条件
```
Baseline  — 現状の最善手（SOTA）
Ablation  — 提案手法の要素を1つずつ取り除いた条件
Proposed  — 提案手法（すべての要素あり）
Oracle    — 上限値（人間評価や理想値）
```

### 4.3 サンプルサイズの計算
```python
# 統計的検出力 (Power) に基づくサンプルサイズ計算
from statsmodels.stats.power import TTestIndPower

analysis = TTestIndPower()
n = analysis.solve_power(
    effect_size=0.5,   # Cohen's d: 0.2=small, 0.5=medium, 0.8=large
    power=0.80,        # 検出力 80%（標準）
    alpha=0.05,        # 有意水準
    alternative='two-sided'
)
print(f"必要なサンプルサイズ（片側）: {n:.0f}")
```

### 4.4 再現性の確保
```python
# ランダムシードの固定（必須）
import random, numpy as np, torch

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
torch.cuda.manual_seed_all(SEED)
# 実験設定はすべてconfigファイルで管理
```

---

## 5. 論文の構成（IMRaD 形式）

### 標準構成
```
Title
Abstract（150-250語）
1. Introduction
2. Related Work / Background
3. Methodology / Proposed Method
4. Experiments
   4.1 Setup
   4.2 Datasets
   4.3 Baselines
   4.4 Results
   4.5 Ablation Study
5. Discussion
6. Conclusion
References
Appendix（任意）
```

---

## 6. 各セクションの書き方

### Abstract（アブストラクト）— 5文構成
```
文1: 研究分野・背景（1文）
文2: 未解決の問題・ギャップ（1文）
文3: 提案手法の概要（1文）
文4: 主要な実験結果・数値（1文）
文5: 意義・インパクト（1文）

例:
"Large language models have demonstrated remarkable capabilities in
code generation tasks. However, existing approaches struggle with
multi-file repository-level code synthesis. We propose RepoFormer,
a hierarchical transformer that incorporates cross-file dependency
graphs during generation. On the HumanEval+ benchmark, RepoFormer
achieves 73.2% pass@1, surpassing the previous SOTA by 8.4 percentage
points. Our work enables reliable automated refactoring of large
codebases with minimal human intervention."
```

### Introduction（序論）— 構成
```
1. Hook: 問題の重要性・動機（2-3文）
2. Problem Statement: 具体的な課題（2-3文）
3. Gap Analysis: 先行研究の限界（3-4文）
4. Contribution: 本研究の貢献（bullet形式で3-5点）
5. Paper Structure: 以降の構成説明（1文）
```

### Contribution の書き方
```markdown
本論文の主要な貢献は以下の通りである:
- **新規手法**: リポジトリレベルの依存グラフを活用する
  階層型Transformerアーキテクチャ（RepoFormer）を提案する。
- **理論的分析**: クロスファイル参照のモデリングに関する
  情報理論的な下限を導出する。
- **実験的検証**: 5つのベンチマークにおいてSOTAを達成し、
  詳細なablation studyにより各コンポーネントの寄与を示す。
- **再現可能性**: コード・モデル・データセットを公開する。
  （https://github.com/...）
```

### Results（結果）の書き方
```markdown
### 主結果

Table 1に示すように、RepoFormerは全ベンチマークにおいて
既存手法を上回った。HumanEval+ではpass@1が73.2%（前SOTA比+8.4pp）、
MBPP+では68.5%（前SOTA比+5.2pp）を達成した。

特筆すべき点として、多ファイル依存が複雑なタスク
（依存深度≥3）においてより大きな改善（+12.3pp）が見られた（Figure 3）。
これはRepoFormerの依存グラフ活用の有効性を示唆する。

*統計的有意性: 両側t検定、α=0.05、p=0.003*
```

### Limitations（限界・制限）— 必ず書く
```markdown
## Limitations

本研究にはいくつかの制限がある。第一に、実験はPython言語のみで
実施しており、他言語への汎化性は検証していない。第二に、
最大100ファイルのリポジトリのみを対象とし、より大規模な
コードベースでの性能は未検証である。第三に、提案手法は
GPT-4へのAPIコストにより、リアルタイム応用では制約がある。
これらの検討は今後の課題とする。
```

---

## 7. 統計解析の標準手順

```python
from scipy import stats
import numpy as np

def report_comparison(group_a: list, group_b: list, metric_name: str):
    """2グループの比較を標準形式でレポート"""
    
    # 記述統計
    print(f"=== {metric_name} ===")
    print(f"Group A: mean={np.mean(group_a):.3f}, std={np.std(group_a):.3f}, n={len(group_a)}")
    print(f"Group B: mean={np.mean(group_b):.3f}, std={np.std(group_b):.3f}, n={len(group_b)}")
    
    # 正規性検定（Shapiro-Wilk）
    _, p_normality = stats.shapiro(group_a)
    
    if p_normality > 0.05:
        # 正規分布 → t検定
        t_stat, p_value = stats.ttest_ind(group_a, group_b)
        test_name = "Independent t-test"
    else:
        # 非正規分布 → Mann-Whitney U検定
        t_stat, p_value = stats.mannwhitneyu(group_a, group_b, alternative='two-sided')
        test_name = "Mann-Whitney U test"
    
    # 効果量（Cohen's d）
    pooled_std = np.sqrt((np.std(group_a)**2 + np.std(group_b)**2) / 2)
    cohens_d = (np.mean(group_a) - np.mean(group_b)) / pooled_std
    
    print(f"\n{test_name}: statistic={t_stat:.3f}, p={p_value:.4f}")
    print(f"Effect size (Cohen's d): {cohens_d:.3f}")
    print(f"Significant (α=0.05): {'Yes ✓' if p_value < 0.05 else 'No ✗'}")
```

---

## 8. 倫理チェックリスト

```
□ IRB/倫理委員会の承認を取得（人間を対象とする場合）
□ インフォームドコンセントを取得
□ データの匿名化・プライバシー保護
□ 利益相反 (Conflict of Interest) の開示
□ 資金提供元の開示
□ 研究データの保管期間・管理方法を明記
□ 著者貢献 (Author Contributions) を記載（CRediT分類推奨）
```
