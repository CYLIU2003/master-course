# 研究課題と貢献

## 研究目的

BEVとICEが併存する移行期のバス営業所を対象に、固定時刻表の全便運行を満たしながら、便単位の動力源・車両割当と、PV・BESS・系統電力を用いた充電計画を接続する二段階法を構築し、その実行可能性と限定されたPV条件差への応答を検証する。

## Research Questions

| ID | 問い | 状態 | 根拠 | 限定 |
| --- | --- | --- | --- | --- |
| RQ1 | BEV/ICE混成営業所で、PV・BESS条件を考慮した二段階配車・充電計画により全264便を満たす実行可能計画を生成できるか | SUPPORTED | 両ケース264/264便、物理VALID、24/24 Rolling、会計eligible | 対象は弦巻、平日1日、固定2ケースである |
| RQ2 | 同一平日運行へ異なるPV曲線を与えたとき、有限候補集合内で選ばれる配車とエネルギー利用はどう変わるか | SUPPORTED_WITH_LIMITATION | 使用BEV 28→21台、BEV担当199→91便、物理配車hash差、22候補行列 | 天候一般ではなく、2025-08-05運行への2本のPV曲線の比較である |
| RQ3 | Stage 1近似目的、有限候補探索、certified gap、Rolling会計に由来する計算・主張上の限界は何か | SUPPORTED | Stage 1 gap 9.5213%/1.6564%、候補22、day-ahead/Rolling分離、claim boundary | 小規模統合oracleと候補範囲感度は未実施である |

## 貢献候補の判定

| 貢献候補 | 判定 | 修論での安全な記述 |
| --- | --- | --- |
| BEV/ICE混成営業所の移行期運用 | SUPPORTED_WITH_LIMITATION | 35 BEV・25 ICEの固定在庫に対する1日実験として示す |
| 便単位の動力源・車両割当 | SUPPORTED | 264便すべてにcanonical vehicle IDとpowertrainが割り当てられ、独立検算済みである |
| 配車と営業所電力運用を接続する二段階法 | SUPPORTED | Stage 1候補生成後に配車を固定し、Stage 2とRollingで電力運用を解く |
| 実時刻表264便規模での検証 | SUPPORTED | 弦巻、WEEKDAY、16路線、264便、15分刻みである |
| 物理・Rolling・会計・provenanceの証拠体系 | SUPPORTED | gateとhashが正本bundleに保存されている |
| 同一運行条件へのPV条件差の評価 | SUPPORTED_WITH_LIMITATION | SUNNYと低PV反実仮想の2ケース内だけで述べる |
| 統合最適化・大域最適性 | NOT_SUPPORTED | Phase 3は逐次二段階であり、統合問題の最適性保証はない |
| 一般的な晴雨効果 | NOT_SUPPORTED | 日付、季節、営業所を跨ぐ標本がない |
| 導入経済性 | NOT_SUPPORTED | 設備費、劣化費、運転士費等がゼロである |
| 9.52%のStage 1 gapでの修論採用 | ADVISOR_DECISION_REQUIRED | 実行可能性結果として採用するか、両ケース1%を要求するか判断が必要である |

## 反証可能な形での結論条件

- RQ1は、欠便、物理違反、Rolling不成立、会計不一致、fallbackまたはrepairが1件でもあれば否定される。
- RQ2は、固定非PV入力が一致しない、PV hashが同一、または選択配車差を正本で追跡できなければ評価不能となる。
- RQ3は、Stage 1 gapを最終費用保証と誤記する、または22候補を全探索と記すと成立しない。
