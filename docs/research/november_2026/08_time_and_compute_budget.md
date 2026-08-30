# 時間・計算予算

## Phase 1

- planning wall上限: 6時間
- solver/Prepare/Rolling: 0
- commit上限: 2
- changed files上限: 15

## Phase 2案

top-level jobは最大9件。`solver run` の数え方は、top-level job数と内部Gurobi optimize回数を併記する。

| tranche | top-level jobs | phase/内部solve | 保守的solver上限 |
| --- | ---: | ---: | ---: |
| oracle 8/12/24 | 3 | 6 | 1,800 s |
| RAIN BASE/EXP1/EXP2 | 3 | candidate/rollingを含む | 9,735 s |
| PV LOW/MEDIUM/HIGH（承認時のみ） | 3 | candidate/rollingを含む | 5,445 s |
| 合計 | 9 | artifactで実数保存 | 16,980 s = 4.72 h |

RAINの保守上限は `Stage1 + candidate_limit * Stage2 cap + 24 * rolling 30 s` で見積もる。実際の共有budgetや早期終了があっても、上限を後から増やさない。PVはBASE相当として見積もる。

## artifact容量

正本RAIN runは約225 MB/248 files、抽出evidence bundleは約0.6 MBだった。full run 1件の最大予約を300 MB、oracle JSON/logを各50 MBとする。

- RAIN 3件: 最大900 MB
- oracle 3件: 最大150 MB
- PV 3件: 最大900 MB
- manifest/hash/比較表余裕: 100 MB
- 全承認時予約: 2.05 GB

空き容量が5 GB未満なら開始しない。20時間後は新しいrunを開始せず、24時間で停止する。solver累積6時間またはtop-level 18件のどちらかへ先に達した時点で打ち切る。
