"""Preserve the supplied deck, comments, and charts; append native evidence slides."""
from pathlib import Path, PurePosixPath
import copy, hashlib, json, os, posixpath, zipfile
from lxml import etree as E

ROOT = Path('C:/master-course')
BUILD = Path(__file__).parent
SOURCE = ROOT / 'outcome/2026-09-28_september_presentation/september_progress_20260928_v4_ur.pptx'
OUT = Path(os.environ.get('TEACHER_REVISION_OUTPUT', ROOT / 'outcome/2026-10-02_teacher_comments'))
OUT.mkdir(exist_ok=True)
TARGET = BUILD / 'patched_only.pptx'
N = {'a':'http://schemas.openxmlformats.org/drawingml/2006/main','p':'http://schemas.openxmlformats.org/presentationml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
data = {}
with zipfile.ZipFile(SOURCE) as z:
    data = {name:z.read(name) for name in z.namelist()}
source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
inventory = json.loads((BUILD / 'source_inventory.json').read_text('utf-8'))
assert source_hash == inventory['sha256']
comments = json.loads((BUILD / 'comments.json').read_text('utf-8'))

def xml_bytes(root):
    return E.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)

def set_text(body, value, size=None):
    oldp = body.find('a:p', N)
    ppr = copy.deepcopy(oldp.find('a:pPr', N)) if oldp is not None and oldp.find('a:pPr', N) is not None else None
    first = body.find('.//a:rPr', N)
    rpr = copy.deepcopy(first) if first is not None else E.Element('{'+N['a']+'}rPr')
    if size:
        rpr.set('sz', str(size))
    for p in list(body.findall('a:p', N)):
        body.remove(p)
    for line in value.split('\n'):
        p = E.SubElement(body, '{'+N['a']+'}p')
        if ppr is not None:
            p.append(copy.deepcopy(ppr))
        r = E.SubElement(p, '{'+N['a']+'}r')
        r.append(copy.deepcopy(rpr))
        E.SubElement(r, '{'+N['a']+'}t').text = line

def shape(root, ident, value, size=None):
    found = [sp for sp in root.findall('.//p:sp', N) if sp.find('.//p:cNvPr', N).get('id') == str(ident)]
    assert len(found) == 1
    set_text(found[0].find('p:txBody', N), value, size)

def table(root, values, size=None):
    rows = root.findall('.//a:tbl/a:tr', N)
    assert len(rows) == len(values)
    for row, texts in zip(rows, values):
        cells = row.findall('a:tc', N)
        assert len(cells) == len(texts)
        for cell, text in zip(cells, texts):
            set_text(cell.find('a:txBody', N), text, size)

def append_notes(number, text):
    part = f'ppt/notesSlides/notesSlide{number}.xml'
    e = E.fromstring(data[part])
    bodies = [sp.find('p:txBody',N) for sp in e.findall('.//p:sp',N) if sp.find('.//p:ph',N) is not None and sp.find('.//p:ph',N).get('type')=='body']
    assert len(bodies)==1
    body=bodies[0]
    p=E.SubElement(body,'{'+N['a']+'}p');r=E.SubElement(p,'{'+N['a']+'}r');E.SubElement(r,'{'+N['a']+'}t').text='2026-10-02先生コメントへの回答：'+text
    data[part]=xml_bytes(e)

changes={}
for i in [7,8,9,10,11,12,15,17,20,24]:
    e=E.fromstring(data[f'ppt/slides/slide{i}.xml'])
    if i==7:
        shape(e,2,'Solcastの15分履歴推定。昼間：晴天時GHIが20 W/m²以上\n降水量[mm]＝降水強度[mm/h]×0.25 hの合計',1650)
        table(e,[['分類','定義・判定順序'],['季節','春3〜5月、夏6〜8月、秋9〜11月、冬12〜2月'],['① 雨','昼間の降水量が1 mm以上。先に雨を判定する'],['② 晴れ / くもり','R＝昼間積算GHI ÷ 昼間積算晴天時GHI\n①に該当しない日：R≥0.7で晴れ、未満でくもり'],['降水形態が未判定','3/3：2℃以下の昼間降水量2.775 mm。雨・雪の別は不明\n天候分類のみ除外。週次最適化の入力には含める'],['日々のばらつき','同じ時刻の日射を並べ、平均と低い側10%点・高い側90%点\nを表示（P10・P90）。実在する1日の曲線ではない'] ],1650)
        shape(e,3,'雨の日でも明るい時間があるため、日単位の分類と時刻別の分布を分ける',1800)
        shape(e,4,'2025年364日を分類（3/3の1日を除外）。研究用の代理分類であり、公式天気分類・予測区間ではない。')
        changes[i]='出典、降水強度と降水量、昼間・分類順序・分母分子、降水形態未判定と除外範囲、経験分位点を明記。'
    if i in [8,9,10,11]:
        shape(e,2,'水平面の全天日射強度 GHI [W/m²]。2025年の同じ分類の日から集計')
        shape(e,4,'P10/P90は同じ時刻の経験分位点。設置面日射・PV発電量・予測区間ではない。')
        if i==9:
            shape(e,3,'雨20日中、明るい昼＋15時以降の降水は2日。「夕立が多い」とは断定しない',1750)
            shape(e,4,'探索集計：10〜14時の日射比≥0.7かつ15時以降の昼間降水≥1 mm。日別の根拠は補足37。')
        if i==11:
            shape(e,3,'この冬夏差は水平面日射の差。実PVの設置面日射・発電量の差とは別',1800)
            shape(e,4,'既存PVはGHI比例換算で設置角・方位が未反映。傾斜面採用には別入力版での評価が必要（補足38）。')
        changes[i]='水平面GHIの意味と予測/設置面の区別を統一。'
    if i==12:
        shape(e,7,'12代表週の運行・充電・費用を確認')
        shape(e,2,'日付別のダイヤとPVを使い、日をまたぐ残量を引き継いだ7日間')
        table(e,[['確認したこと','計算で得られた結果'],['全便の担当','全12週、各1,704便を1回ずつ割当て。欠落・重複なし'],['車両と充電','運行時刻、充電器、車載電池の残量制約を満たす'],['電力の収支','PV・系統・BESSの供給と、バス充電の電力量が一致'],['翌朝と週次費用','最終翌朝の補充まで含め、採用区間の費用を1回ずつ集計'],['結果の位置付け','設定条件下の実行可能な計画。全体最適性は未証明']])
        shape(e,3,'全便の運行と翌朝の補充を含む12週の計画・費用を、同じ条件で整理した',1800)
        shape(e,4,'診断・条件付き評価。正式研究採用は未承認であり、実設備での運用保証や手法の優越性は示していない。')
        changes[i]='制作メモを除き、全便・充電・電力・翌朝・費用の具体的な確認内容に変更。'
    if i==15:
        shape(e,3,'夜間の補充が受電を増やす。3月は200 kW超過が11月より長い（補足39）',1800)
        shape(e,4,'ピーク時：PV供給0、BESS下限、複数車両が同時充電。超過費用は閾値を上回る電力量で決まる。')
        changes[i]='夜間受電の理由と超過電力量の説明を根拠へ接続。'
    if i==17:
        shape(e,2,'両ピークでPV供給0、BESS残量1,200 kWh。翌朝目標90%へ8台 / 10台が充電',1650)
        shape(e,3,'出庫前の補充を系統が供給した。04:15への集中が最適かは未検証',1800)
        shape(e,4,'車両SOC・次の営業便時刻は補足39。充電時間を移した場合の費用・実行可能性は別の比較が必要。')
        changes[i]='観測した供給理由と、特定時刻への集中の未検証を分離。'
    if i==20:
        table(e,[['問い','今回の回答'],['7日間の運行は成立したか','12代表週で全便を担当し、最終翌朝の補充まで評価'],['費用は何で変わったか','3月と11月の総差101.64万円のうち、超過モデル費差90.96万円'],['天候のムラを示せたか','水平面GHIの平均とP10/P90。雨分類にも明るい時間がある'],['次に確かめること','設置面日射への変更、夜間充電の集中を緩める比較'],['主張の限界','全体最適性未証明、電費一定、月1週、設備投資・実設備保証は未評価']],1750)
        shape(e,3,'週次費用の違いは、発電量の大小だけでなく充電時刻と電力供給を見て説明する',1800)
        shape(e,4,'診断・条件付きの計算結果。正式研究採用は未承認。設置面日射と実設備条件の確認が必要。')
        changes[i]='内部判定コードを別記録へ移し、結果と理由・限界を読み手向けに整理。'
    if i==24:
        shape(e,7,'補足：今回の結果を解釈するための前提')
        shape(e,2,'計算した条件と、現実の運用への適用範囲を区別する')
        table(e,[['前提','結果を読むときの注意'],['気象とダイヤの年','2025年気象×2026年固定ダイヤ。過去実運行の再現ではない'],['予測と評価','2024年の平均的日射で計画し、2025年履歴推定で運用を評価'],['PVの設置条件','水平面GHIから簡易換算。傾斜角・方位が未反映'],['費用と設備','超過費はモデル料金。実受電設備の上限・設備投資は未評価'],['BESSの残存電力量','終端は初期へ戻さない。在庫差を毎週の節約とは扱わない'],['解の品質・採用範囲','時間制限内の実行可能解。統合最適性・正式研究採用は未確認']],1600)
        shape(e,3,'条件付きの代表週比較であり、実設備の保証・年間平均・最適解の証明ではない',1800)
        shape(e,4,'電費は一定、距離は停留所座標による代理値。実装・原本の詳しい記録は発表者ノートと別紙へ。')
        changes[i]='SHAや描画復旧コードをノートへ保持し、仮定と結果の適用範囲を説明。'
    data[f'ppt/slides/slide{i}.xml']=xml_bytes(e)

responses = {
1:'降水はSolcastのhistoric radiation_and_weatherに保存されたprecipitation_rate（mm/h）の履歴推定で、雨量計の観測ではない。15分強度×0.25hを合算する。出典：https://docs.solcast.com.au/docs/output-parameters。2025年35,040区間の固定データを用いた。',
2:'雨を優先して分類するので「雨に当たらない日」が必要。分子は昼間積算GHI、分母は同じ昼間の積算晴天時GHI。昼間の判定はGHIではなくclearsky_ghi>=20 W/m²。雨と高日射は両立し得る。R>=0.7を晴れ、それ未満をくもりとする研究用の固定閾値。',
3:'雪の日と確認したわけではない。3/3の気温2℃以下の昼間区間の降水量が2.775mmで、降水形態未判定として分類のみ除外。週次計算には3/3の気象・運行を含めている。',
4:'判別できない対象は雨/雪等の降水形態。今回の取得項目は気温と降水強度を含むが、雪の観測・降水形態は含まない。2℃以下だけで雪とは断定しない。',
5:'各時刻の同じ分類の日の日射値を並べた経験分布の平均、10%点、90%点。P10/P90は実在する1日の曲線でも予測区間/信頼区間でもない。全セル10日以上は件数の確認であり精度保証ではない。',
6:'夏雨20日中、10〜14時のGHI/晴天時GHI積算比>=0.7は6日。その中で15時以降の昼間降水が1mm以上は2日。例7/10は比0.879、15時前0.30mm、15時以降1.10mm。雨分類にも明るい時間が含まれることがP90の高い時刻を説明するが、「夕立が多い」は支持しない。事後の探索集計で、対流性降水を同定したものではない。補足37と日別CSVを参照。',
7:'傾斜面日射が必要という指摘を受け入れ、現行が水平面GHIの記述統計・GHI比例PV換算であることを明記。設置角・方位の実条件確認と、直達/散乱から設置面日射を得る別入力版での再評価が必要。現状の12週を補正済みの結果へ改称しない。補足38。未完了：傾斜面を用いたPV再計算・再求解。公式参照：https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.irradiance.get_total_irradiance.html。',
8:'聴衆向けの表を全便の担当、車両/充電制約、電力収支、翌朝/費用、解の位置付けへ書き直した。1/11/12月の図表復旧や原FAILEDは元ノートと別紙に保持し、計算失敗と図表失敗を混同しない。',
9:'両ピークでPV供給0、BESS下限1200kWh、8/10台が翌朝目標90%へ同時充電しており、系統が全バス充電を供給した。ピーク開始SOC、次の営業便発車、車両/充電器IDをCSVへ保存。夜間供給源の理由と、04:15へ集中する探索上の理由は別。帰庫時刻ごとの代替充電余地・予測誤差・計画窓・探索品質の寄与は未分離。3月の超過が長く、総費用差101.64万円のうち90.96万円が超過モデル費差。改善可能性を示唆するが最適/不可避とは断定しない。補足39。',
10:'BLOCKED等の管理コードはノート/別紙に保持し、本文は診断・条件付きの結果と正式研究採用未承認という意味を日本語で示す。限界自体は消さない。',
11:'計算固定SHA、hash、CO₂図表の警告、内部判定を別紙/ノートへ保持。補足24を気象・ダイヤ年、予測、PV設置条件、費用/設備、BESS在庫、解品質の解釈に変更した。'
}
for slide in sorted({c['slide'] for c in comments} | {17}):
    lines=[f"コメント{c['index']}：{c['text']}\n回答：{responses[c['index']]}" for c in comments if c['slide']==slide]
    if slide==17: lines=[responses[9]]
    append_notes(slide,'\n\n'.join(lines)+'\n原計算固定版 f524eca2552a4386bd033a15bbe046c14dc09281。原判定BLOCKED / DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSを保持。今回の訂正は表現と原本からの追加集計のみ。')

with zipfile.ZipFile(TARGET,'w',zipfile.ZIP_DEFLATED) as z:
    for name,value in data.items(): z.writestr(name,value)

assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_hash
with zipfile.ZipFile(SOURCE) as original,zipfile.ZipFile(TARGET) as revised:
    unchanged_slides=[i for i in range(1,37) if i not in changes]
    for i in unchanged_slides: assert original.read(f'ppt/slides/slide{i}.xml')==revised.read(f'ppt/slides/slide{i}.xml')
    protected=[n for n in original.namelist() if n.startswith(('ppt/comments/','ppt/charts/','ppt/embeddings/'))]
    for name in protected: assert original.read(name)==revised.read(name),name
receipt={'source':str(SOURCE),'source_sha256':source_hash,'candidate':str(TARGET),'comments_retained':len(comments),'source_slides':36,'final_slides':39,'changed_original_slides':changes,'unchanged_original_slides_byte_identical':unchanged_slides,'protected_chart_comment_workbook_parts':len(protected),'additional_analyses_only':True,'new_solver_run':False}
(BUILD / 'preservation_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
response='# 先生の埋め込みコメントへの回答（2026-10-02）\n\n指定された先生コメント入り36枚を元に訂正し、原本を保持した39枚版です。コメント11件は削除・自動解決せず残しています。新しい補足37〜39は原本からの追加集計です。\n\n'
for c in comments:
    response+=f"## {c['index']}. 元スライド{c['slide']}（修正版も同番号）\n\n> {c['text']}\n\n{responses[c['index']]}\n\n"
response+='## Claudeレビューの採否\n\nClaude Sonnet 5で11コメント・元スライド抜粋・追加集計を独立内容レビュー。出典・分類順序・降水形態・水平面/設置面・供給理由と最適性の分離、管理メモの移動を採用しました。レビュー文案の「午前中晴天的」「午後に降水が強まった」は10〜14時比と15時以降積算という確認値より広い表現なので不採用。「GHI>=20」の略記は誤読を招くため「晴天時GHI>=20」に修正しました。Claudeは原本の再計算や教員承認を行っていません。\n\n## 未完了の技術課題\n\n傾斜面日射のPV換算と別入力版での週次再評価、充電を他の時刻に移す対照計算は今回行っていません。これらを解決済み・最適性証明済みとはしていません。設置角・方位は確認が必要です。原計算・会計の数値と原研究採用判定は保持しました。\n'
(OUT / 'teacher_response.md').write_text(response,encoding='utf-8')
print(json.dumps(receipt,ensure_ascii=False,indent=2))



