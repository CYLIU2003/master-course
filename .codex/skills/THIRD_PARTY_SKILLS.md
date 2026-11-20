# 外部から取り込んだスキル（2026-11-20）

利用者の依頼（11/20）：次の11リポジトリのスキルを取り入れる。
nature-skills、research-writing-skill、AI-research-tools、academic-research-skills-codex、claude-scholar、Auto-Empirical-Research-Skills、supervisor-skills、scientific-research-skills、FAROS、paperbanana、Awesome-Journal-Skills。

## 取り込み方

- 各リポジトリを浅く clone し（作業用の一時フォルダ、プロジェクトの外）、ライセンスと SKILL.md を読んでから選んだ。
- 取り込んだのは文章（`*.md`、`*.yaml`）だけ。`scripts/`、`tests/`、`agents/` は入れていない。外部のコードをこのリポジトリで実行しないため。
- 各フォルダに上流のライセンスを `LICENSE.upstream` として置いた。中身は上流のまま変えていない。
- この研究で使うときも AGENTS.md の規則が優先する（DIAGNOSTIC の表示、最適性を主張しないこと、数値を作らないこと、など）。外部スキルの指示がこれとぶつかる場合は AGENTS.md に従う。

## 取り込んだもの

| スキル | 上流（コミット） | ライセンス | 用途 |
|---|---|---|---|
| nature-reviewer | Yuan1z0825/nature-skills `skills/nature-reviewer`（9bd1d082） | Apache-2.0 | 模擬査読、数値の整合の監査（forensic consistency audit） |
| nature-polishing | 同 `skills/nature-polishing` | Apache-2.0 | 英文の推敲（事実と主張の範囲を変えない） |
| nature-shared | 同 `skills/nature-shared` | Apache-2.0 | 上の2つが参照する共通資料。`core/consistency-sweep.md` が触れる `scripts/check_consistency.py` は取り込んでいないので、整合の確認は手で行う |
| paper-self-review | Galaxy-Dawn/claude-scholar `skills/paper-self-review`（d394fb59） | MIT | 主張と根拠の監査（keep / weaken / revise / remove） |
| writing-anti-ai | 同 `skills/writing-anti-ai` | MIT | AI らしい言い回しの除去（英語・中国語） |
| pre-submission-reviewer | hkustdial/supervisor-skills `skills/pre-submission-reviewer`（4bd3fef3） | CC BY-NC-SA 4.0（リポジトリ）。SKILL.md の表記は CC-BY-4.0 | 提出前の5観点レビュー（CRITICAL / MAJOR / MINOR） |
| figure-designer | 同 `skills/figure-designer` | 同上 | 図の監査（文字の大きさ、色覚、キャプションだけで読めるか、軸の範囲） |
| peer-review | Norman-bury/research-writing-skill `skills/peer-review`（6f795955） | MIT | 査読のチェックリスト（中国語） |

CC BY-NC-SA は非営利の研究利用に限る。

## 取り込まなかったもの

| リポジトリ | 理由 |
|---|---|
| bighuang624/AI-research-tools | スキルではなく、ツールへのリンク集（SKILL.md なし） |
| OpenNSWM-Lab/FAROS | スキルではなく、サーバーとフロントエンドを持つシステム（SKILL.md なし）。動かすには外部コードの実行が必要 |
| Imbad0202/academic-research-skills-codex | 大きな1スキルの総合パッケージ（CC BY-NC 4.0）。上の監査用スキルと役割が重なる |
| brycewang-stanford/Auto-Empirical-Research-Skills | 計量経済の実証分析（Stata・R・Python の回帰）向けで、この研究の手法と合わない |
| brycewang-stanford/Awesome-Journal-Skills | 290件の学会・ジャーナル別スキル。電気学会（IEEJ）向けのものはない。リポジトリ全体のライセンス表記もない |
| llmsresearch/paperbanana、jxtse academic-figure-generation | 外部の画像生成 API（Gemini・OpenRouter）の API キーと MCP サーバーが必要。研究データを外部に送ることになる |
| claude-scholar publication-chart-skill | 外部パッケージ（pubfig・pubtab）の pip 導入を指示する |
| nature-figure | 38本のスクリプトを含み、34 MB と大きい。図の監査は figure-designer で足りる |
| その他（文献検索、Zotero、Obsidian、LaTeX、特許、医学・法学向けなど） | この研究の今の作業（ポスター・資料の監査）に関係しない |

Claude Code からは `.claude/skills/<name>/SKILL.md`（ここへの案内）経由で読み込む。正本はこのフォルダ。
