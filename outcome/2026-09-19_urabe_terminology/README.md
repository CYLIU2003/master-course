# 占部先生の指摘への対応：用語と定義の統一

2026年9月19日7:23のSlack返信にある、受電ピークの定義と名称の揺れに対応した24枚の改訂版です。編集元はユーザーが更新した9月18日版です。原本を保持し、ページ構成と計算結果を引き継いでいます。

- [PowerPoint](monthly_progress_20260919_terms_v2.pptx)
- [閲覧用PDF](monthly_progress_20260919_terms_v2.pdf)
- [返信案（未送信）](slack_reply_draft.md)
- [発表者ノート](speaker_notes.md)
- [説明書](reader_guide.md)
- [今後の作成ルール SKILL.md](../../.codex/skills/research-presentation/SKILL.md)
- [統一用語表](../../.codex/skills/research-presentation/references/monthly-terminology.md)

## 指摘への回答

P9の「最大15分平均受電電力」は受電ピークを表していました。P7、P9、P13、補足P20・21を含め、正式名称を**受電ピーク［kW］**に統一しました。定義は**1週間の672個の15分平均受電電力の最大値**です。

「週間平均受電電力」は受電ゼロを含む168時間平均、「週間購入電力量」は1週間の積算値です。超過電力量・超過時間・超過ペナルティも別の指標として扱います。本文、表、グラフ、ノート、埋め込みブック、同梱説明書を照合しています。

## 変更範囲と根拠

- 元のユーザー編集済みPPTXのSHA256：`5b08eacba4d341b539cbdd048ffc644edb459794808a2ca7f40f98659c6aa620`。
- 改訂PPTXのSHA256：`51a42771ab406476893267f6c34ee9571f3bbf0b506248e4e5dfe392822b28fc`。
- 原データは固定7c7c2334の[詳細集計](../2026-09-18_urabe_followup/analysis.json)と[主結果](../../docs/notes/SHIBU21_23_MONTHLY_PHASE_SEARCH_RESULTS_20260915.json)です。今回の変更は用語・説明の整理です。
- 元ファイルの保存によって浮動小数の表記が異なっていたグラフキャッシュ336点を、参照先Excelと同じ文字列表現にそろえました。すべて元と同じ数値であることを照合し、ブックの数値・実験結果は変更していません。
- PowerPointで24ページを開いてレンダリングし、PPTXからPDFを生成しました。ネイティブの表・7グラフ・7ブックを保持しています。

モデル、凍結出力、研究上の採用状態は変更していません。DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS、研究採用BLOCKEDを維持しています。Slack返信・メールは未送信です。
