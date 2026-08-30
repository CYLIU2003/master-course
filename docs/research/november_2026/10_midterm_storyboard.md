# 修士中間発表 storyboard

12枚、10～15分共通の骨格とする。

| # | slide | 中心メッセージ | evidence |
| ---: | --- | --- | --- |
| 1 | 社会背景 | バス脱炭素化には車両と営業所電力を同時に扱う必要 | literature matrix |
| 2 | 研究gap | 配車・充電・PV/BESS・監査の接続が課題 | Related Work |
| 3 | 研究目的/RQ | 実行可能な二段階計画と限界の定量化 | RQ table |
| 4 | 対象 | 弦巻、WEEKDAY 264便、混成fleet | Prepared contract |
| 5 | model boundary | Stage 1候補生成とStage 2固定配車recourse | equation/code trace |
| 6 | 候補選択 | canonical cost→使用台数→hash | candidate artifacts |
| 7 | 検証鎖 | 物理、24/24 Rolling、会計を分離 | gate artifacts |
| 8 | 高/低PV結果 | 28/4対21/11、199対91 BEV便 | frozen summary |
| 9 | 96-slot flow | grid/PV/BESS/SOCの時系列差 | canonical figures |
| 10 | 内的妥当性 | 小規模oracle計画/結果 | P0-B artifact or blocker |
| 11 | 選択安定性 | RAIN margin 566.62円と範囲感度 | P0-A artifact or blocker |
| 12 | 限界と工程 | gap、有限候補、単一運行日、10月freeze | decision register |

発表では完成事項と未完成事項を同じslideで区別する。追加実験が未完なら、結果欄を空のままにせず `NOT RUN / exact blocker` と表示する。Stage 1 certified gap 9.52%/1.66%をRolling費用gapと呼ばない。
