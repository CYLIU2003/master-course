/** Build the July monthly progress deck from the established 18-slide frame. */

import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";


const REPO_ROOT = "C:\\master-course";
const DEFAULT_WORKSPACE =
  "C:\\Users\\RTDS_admin\\AppData\\Local\\Temp\\codex-presentations\\manual-20260718\\july-monthly-progress\\tmp";
const TEMPLATE_STARTER_NAME = "template-starter.pptx";
const OUTPUT_PPTX = path.join(
  REPO_ROOT,
  "docs",
  "presentations",
  "monthly_progress_20260718.pptx",
);
const FIGURE_DIR = path.join(REPO_ROOT, "output", "monthly_progress_202607", "figures");


function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    args[token.slice(2)] = argv[index + 1];
    index += 1;
  }
  return args;
}


async function importArtifactTool(workspace) {
  const modulePath = path.join(
    workspace,
    "node_modules",
    "@oai",
    "artifact-tool",
    "dist",
    "artifact_tool.mjs",
  );
  return import(pathToFileURL(modulePath).href);
}


let inheritedAnchorLocators = new Map();


function resolveInheritedElement(presentation, anchorId) {
  const locator = inheritedAnchorLocators.get(anchorId);
  if (!locator) return presentation.resolve(anchorId);
  const slide = slideAt(presentation, locator.slide - 1);
  const target = slide.elements.items.find((element) => element.name === locator.name);
  if (!target) {
    throw new Error(
      `missing inherited element: ${anchorId} (slide ${locator.slide}, ${locator.name})`,
    );
  }
  return target;
}


function setText(presentation, anchorId, value) {
  const target = resolveInheritedElement(presentation, anchorId);
  target.text = value;
}


function setTable(presentation, anchorId, rows) {
  const table = resolveInheritedElement(presentation, anchorId);
  for (let row = 0; row < rows.length; row += 1) {
    for (let column = 0; column < rows[row].length; column += 1) {
      table.cells.set(row, column, rows[row][column]);
    }
  }
}


async function replaceImage(presentation, anchorId, imagePath, alt) {
  const target = resolveInheritedElement(presentation, anchorId);
  const frame = target.frame;
  const crop = target.crop;
  const geometry = target.geometry;
  const borderRadius = target.borderRadius;
  const rotation = target.rotation;
  const flipHorizontal = target.flipHorizontal;
  const flipVertical = target.flipVertical;
  const lockAspectRatio = target.lockAspectRatio;
  const bytes = new Uint8Array(await fs.readFile(imagePath));
  target.replace({ blob: bytes, contentType: "image/png", alt, fit: "contain" });
  target.frame = frame;
  target.crop = crop;
  target.geometry = geometry;
  target.borderRadius = borderRadius;
  target.rotation = rotation;
  target.flipHorizontal = flipHorizontal;
  target.flipVertical = flipVertical;
  target.lockAspectRatio = lockAspectRatio;
}


function slideAt(presentation, index) {
  if (Array.isArray(presentation.slides?.items)) return presentation.slides.items[index];
  return presentation.slides.getItem(index);
}


function setFooter(presentation, anchorId, slideNumber) {
  setText(presentation, anchorId, `EVバス月間進捗　2026-07-18　${slideNumber}/18`);
}


function setNotes(presentation, slideNumber, notes) {
  const slide = slideAt(presentation, slideNumber - 1);
  slide.speakerNotes.textFrame.setText(notes);
}


async function readNdjson(filePath) {
  const content = await fs.readFile(filePath, "utf8");
  return content
    .split(/\r?\n/u)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}


async function buildInheritedAnchorLocators(workspace) {
  const sourceRecords = await readNdjson(
    path.join(workspace, "july-deck-inspect-full", "template-inspect.ndjson"),
  );
  const editableKinds = new Set(["textbox", "table", "image"]);
  const mapping = new Map();
  for (const record of sourceRecords.filter((item) => editableKinds.has(item.kind))) {
    mapping.set(record.id, {
      slide: record.slide,
      kind: record.kind,
      name: record.name,
    });
  }
  return mapping;
}


function applyCoreText(presentation) {
  setText(presentation, "sh/sryl4zqx", "7月 月間進捗報告");
  setText(presentation, "sh/fu94fe98", "電気バスを止めずに、太陽光を活かして充電するための計画づくり");
  setText(presentation, "sh/utg3698n", "2026年7月18日　月間進捗報告");
  setText(presentation, "sh/hofulsf2", "進捗結果は output/2026-07-17 の2回の計算に限定");

  setText(presentation, "sh/9072xkry", "電気バスは、交通と電力の両方を変える取り組み");
  setFooter(presentation, "sh/r65knqtk", 2);
  setTable(presentation, "tb/l8n2t07y", [
    ["社会の変化", "必要な対応", "電気バスとの関係", "本研究で扱うこと"],
    ["脱炭素", "交通と電力の排出を減らす", "ディーゼル車から電気へ", "運行時の電力も評価"],
    ["再生可能エネルギー", "太陽光を地域で使う", "昼間の充電に活用できる", "発電時刻と充電を合わせる"],
    ["電力の変動", "晴天・雨天の差に備える", "使える太陽光が毎日変わる", "予測を更新して充電を見直す"],
    ["公共交通の責任", "決めた便を止めない", "充電不足が運休につながる", "全便を走れるか確認する"],
    ["設備の制約", "充電器と受電量を守る", "同時充電には上限がある", "混雑しない時間を選ぶ"],
  ]);
  setText(
    presentation,
    "sh/9wnqhczy",
    "要点｜電気バスは、車両を電動化するだけでなく、いつ・どの電気で充電するかまで考える必要がある。",
  );

  setText(presentation, "sh/cza94vmx", "研究背景：運行と充電は別々には決められない");
  setFooter(presentation, "sh/m5cra54z", 3);
  setTable(presentation, "tb/lgvu9wbm", [
    ["現場で起こること", "単純に決められない理由", "必要な対応"],
    ["バスは決まった時刻に走る", "運行中は営業所で充電できない", "停車時間だけを充電候補にする"],
    ["電池容量には限りがある", "次の便までに必要量を確保する", "車両ごとの残量を追跡する"],
    ["太陽光は天候で変わる", "前日の予測どおりとは限らない", "当日に予測を更新する"],
    ["充電器の台数は限られる", "同じ時間に集中すると使えない", "充電時間を分散する"],
    ["電気料金は時間で変わる", "充電時刻で費用が変わる", "安い時間と最大電力を考える"],
  ]);
  setText(presentation, "sh/m1c3mlsn", "研究上の課題");
  setText(presentation, "sh/943mhgre", "前日に決めた計画だけでは");
  setText(presentation, "sh/83ulovat", "当日の変化");
  setText(presentation, "sh/a5c3ql8z", "に対応しにくい");
  setText(presentation, "sh/x8nml0ra", "そこで、一日全体を計画した後、毎時間充電を見直す");
  setText(presentation, "sh/ja54na9g", "要点｜運行予定を守りながら、最新の発電量と電池残量に合わせて充電を調整する。");

  setText(presentation, "sh/1cj2d8b6", "研究目的：止めない・無駄にしない・説明できる");
  setFooter(presentation, "sh/3ihk3et8", 4);
  setTable(presentation, "tb/1g3ex4zu", [
    ["目標", "具体的に行うこと", "成功の判断"],
    ["運行を止めない", "全便に車両を割り当てる", "未担当便が0便"],
    ["充電切れを防ぐ", "各車両の電池残量を追う", "最低残量を下回らない"],
    ["太陽光を活かす", "発電中に充電または蓄電する", "電気の行き先を説明できる"],
    ["設備を守る", "充電器台数と受電上限を確認する", "設備違反が0件"],
    ["費用とCO₂を減らす", "電源と充電時刻を選ぶ", "同じ条件で比較できる"],
    ["結果を信頼できる形にする", "別計算で運行と電力を再確認する", "全出力の数値が一致する"],
  ]);
  setText(
    presentation,
    "sh/5cva1cfq",
    "要点｜安さだけではなく、全便運行・電池残量・設備上限を守った結果だけを採用する。",
  );

  setText(presentation, "sh/dgbulwnm", "手法：一日全体を計画し、毎時間充電を見直す");
  setFooter(presentation, "sh/n6dcr65o", 5);
  setText(presentation, "sh/w32dkbuh", "① 運行前：一日全体の計画");
  setText(
    presentation,
    "sh/x4vedgvm",
    "どのバスがどの便を走るかを決める\n一日分の充電予定を作る\n前日の太陽光予測と料金を使う",
  );
  setText(presentation, "sh/58vehgvy", "② 運行中：1時間ごとの見直し");
  setText(
    presentation,
    "sh/i54fmlc7",
    "車両の担当便は変えない\n最新の電池残量と太陽光予測を入れる\n残り時間の充電予定を作り直す",
  );
  setText(presentation, "sh/sb6xsvu9", "分かりにくい言葉を日常語に置き換える");
  setText(
    presentation,
    "sh/tcfel0vu",
    "『充電量の下界』＝ 走り切るために、少なくとも必要と見積もった充電量",
  );
  setText(
    presentation,
    "sh/hgrmpwj2",
    "朝の車両電池を差し引いて見積もる。ただし、充電時刻や充電器の混雑はまだ確認していない。\n\n『初期BESS余剰』＝ 朝の営業所蓄電池のうち、終業時に残す目標を超える部分。朝300 kWh・終業時300 kWhなら0 kWh。",
  );
  setText(
    presentation,
    "sh/fe94nm1w",
    "要点｜最初の計画を土台にし、毎時間変えるのは充電予定だけ。運行便を途中で入れ替えない。",
  );

  setText(presentation, "sh/yhg7epsj", "① 一日全体の計画で、何を入力し何を決めるか");
  setFooter(presentation, "sh/oryp8fah", 6);
  setTable(presentation, "tb/1cji5432", [
    ["入力する情報", "内容"],
    ["時刻表", "出発・到着時刻と運行区間"],
    ["車両", "電気バス・ディーゼルバスの台数"],
    ["車両の電池", "朝の残量・使える範囲"],
    ["営業所設備", "充電器・受電上限・蓄電池"],
    ["太陽光予測", "時間ごとの発電見込み"],
    ["料金・CO₂", "電気と燃料の評価条件"],
    ["終業時の目標", "翌日に残す電池量"],
    ["時間の細かさ", "何分ごとに判断するか"],
  ]);
  setTable(presentation, "tb/ql8zq5kf", [
    ["決めること", "内容"],
    ["担当車両", "各便をどの車両が走るか"],
    ["車両の使い分け", "電気・ディーゼルのどちらを使うか"],
    ["充電時刻", "営業所にいる間のいつ充電するか"],
    ["充電量", "出発前にどれだけ充電するか"],
    ["電気の出どころ", "太陽光・系統・蓄電池の使い分け"],
    ["同時充電", "充電器の台数を超えない組合せ"],
    ["最大受電", "電力が集中しすぎない計画"],
    ["一日の費用", "電気・燃料・車両利用の合計"],
    ["確認結果", "全便を実際に走れるか"],
  ]);
  setText(
    presentation,
    "sh/v2tcn650",
    "要点｜車両の担当と充電を同じ一日の中で確認し、走れない計画は結果として採用しない。",
  );

  setText(presentation, "sh/cb2tkvap", "② 1時間ごとの見直しで、何を更新し何を固定するか");
  setFooter(presentation, "sh/eh0ba1sr", 7);
  setTable(presentation, "tb/baloj6xo", [
    ["毎正時に更新する情報", "具体例"],
    ["車両の電池残量", "実際に残っている量"],
    ["営業所蓄電池の残量", "現在使える量"],
    ["太陽光の予測", "最新の天気予報"],
    ["すでに使った最大電力", "その日ここまでの記録"],
    ["現在時刻", "実行済みと未実行を分ける"],
    ["運行状況", "遅れや実績を確認する"],
  ]);
  setTable(presentation, "tb/sfa5gryp", [
    ["途中で変えないもの", "理由"],
    ["時刻表", "乗客サービスを守るため"],
    ["担当車両", "日中の急な入替えを避けるため"],
    ["終了した運行", "二重に数えないため"],
    ["終了した充電", "費用と電池量を二重計上しないため"],
    ["設備の台数", "現場の条件を変えないため"],
    ["電池の安全範囲", "故障や運休を防ぐため"],
    ["一日の終了時刻", "同じ評価範囲を保つため"],
  ]);
  setText(presentation, "sh/xcz2l03q", "1時間ごとの動き");
  setText(presentation, "sh/cbq1sv25", "残りの一日を計算し直す");
  setText(presentation, "sh/n6x0fqlo", "次の1時間だけ実行し、また最新情報で見直す");
  setText(
    presentation,
    "sh/p8fih03e",
    "要点｜『1時間の最適化』とは、毎時間、残りの充電計画を更新して次の1時間だけ実行すること。",
  );
}


function applyEvidenceSlideText(presentation) {
  setText(presentation, "sh/18byd4zy", "対策① 失敗した計算を、正常な結果として見せない");
  setFooter(presentation, "sh/je9g3ahk", 8);
  setText(presentation, "sh/98rehwve", "見つかった問題");
  setText(presentation, "sh/m5gvmhwn", "正式判定：264便走れない\n集計表示：0便\n2回とも同じ食い違い");
  setText(presentation, "sh/n6pwfmd8", "走れない場合、費用を0円と表示せず『評価できない』とする。");
  setText(
    presentation,
    "sh/1k7edwv2",
    "要点｜正式判定を基準に、運行結果・費用・資料の表示をすべて同じ判定へそろえた。",
  );

  setText(presentation, "sh/1cfmhgne", "対策② 候補を作った後、本当に走れるかを再確認する");
  setFooter(presentation, "sh/bih4na5w", 9);
  setText(presentation, "sh/p0ji9kf2", "読み方");
  setText(presentation, "sh/2xsjepgb", "候補づくり：264便\n充電確認：成立せず\n正式結果：0便");
  setText(presentation, "sh/3y107axw", "候補だけを、運行できた結果として使わない。");
  setText(
    presentation,
    "sh/do3id4fy",
    "要点｜『便を割り当てられた』だけでは不十分。充電器と電池残量まで確認して初めて正式結果になる。",
  );

  setText(presentation, "sh/xc3mho32", "対策③ 計算がどこまで絞り込めたかを表示する");
  setFooter(presentation, "sh/725onyl4", 10);
  setText(presentation, "sh/d87uxg3m", "目標の残り幅");
  setText(presentation, "sh/q5gb21kb", "10%");
  setText(presentation, "sh/r6pcv6lw", "目標値");
  setText(presentation, "sh/1cru1g3y", "今回の残り幅");
  setText(presentation, "sh/e9gb61k7", "48.37%");
  setText(presentation, "sh/fapcz6ls", "2回とも同じ");
  setText(presentation, "sh/p0ru503u", "計算時間");
  setText(presentation, "sh/xwnupgvy", "候補づくり 約750秒");
  setText(
    presentation,
    "sh/bu5cnqd8",
    "要点｜目標10%に対して48.37%残っており、『最もよい計画』まで絞れたとは言えない。",
  );

  setText(presentation, "sh/xcryxg7y", "太陽光の条件は違うが、効果はまだ比べられない");
  setFooter(presentation, "sh/72t03qp0", 11);
  setText(presentation, "sh/9gza9sze", "PV発電見込み高");
  setText(presentation, "sh/mdobedg3", "614.7");
  setText(presentation, "sh/nehs7iho", "kWh/日・最大81.3 kW");
  setText(presentation, "sh/1cfa58zi", "PV発電見込み低");
  setText(presentation, "sh/epobatgr", "101.1");
  setText(presentation, "sh/zaxs3yhc", "kWh/日・最大12.9 kW");
  setText(presentation, "sh/cn6t83y1", "天候補正に必要な\n時間別データが不足");
  setText(
    presentation,
    "sh/tsnip0ny",
    "要点｜示せるのは発電見込みの違いまで。バスや営業所蓄電池へ何kWh使えたかは未評価。",
  );

  setText(presentation, "sh/1gbm9s3a", "対策④ 計算を速くするため、便のつなぎ候補を減らした");
  setFooter(presentation, "sh/b6d4f2lc", 12);
  setText(presentation, "sh/xw3q94ne", "すべての候補");
  setText(presentation, "sh/atc7epon", "678,600本");
  setText(presentation, "sh/bulo7u58", "便から次の便への組合せ");
  setText(presentation, "sh/9sj65kn2", "計算に残した候補");
  setText(presentation, "sh/mps7a5or", "113,712本");
  setText(presentation, "sh/nq1o3a5w", "各便の次候補を最大8本に制限");
  setText(presentation, "sh/0nap8f6l", "83.2%削減／元の計画にある12本は残した");
  setText(
    presentation,
    "sh/hkbm5wzu",
    "要点｜速くなる一方、より良い組合せを消す可能性があるため、候補数を変えて結果を比較する。",
  );

  setText(presentation, "sh/q50nydsj", "対策⑤ 結果の明細があるか確認する");
  setFooter(presentation, "sh/gzy5s3a1", 13);
  setText(presentation, "sh/gb6x0zm9", "運行・充電の明細");
  setText(presentation, "sh/vaxg7ulo", "0行");
  setText(presentation, "sh/u9ofyp43", "車両担当・充電・電池残量の記録なし");
  setText(presentation, "sh/876xwfmx", "入力／失敗の明細");
  setText(presentation, "sh/7mdg3als", "24／264行");
  setText(presentation, "sh/6l4fu547", "PV入力24・未充足便264");
  setText(presentation, "sh/lkvy103m", "2回とも同じ\n運行の指標は作れない");
  setText(
    presentation,
    "sh/cnqh8fux",
    "要点｜明細0行は『実績が0』ではなく『結果が作られていない』。0円や0kWhへ置き換えない。",
  );

  setText(presentation, "sh/xc7eds76", "先行研究のような図は、正式な結果がそろってから作る");
  setFooter(presentation, "sh/zi5c3y98", 14);
  setText(presentation, "sh/x4ni9ofy", "今回載せられる確認図");
  setText(presentation, "sh/a1wze9g7", "3種類");
  setText(presentation, "sh/b2507exs", "計算状況・便数・PV入力");
  setText(presentation, "sh/ls7idofu", "まだ載せられない結果図");
  setText(presentation, "sh/y5wjitgj", "5種類");
  setText(presentation, "sh/z650byxo", "運行／電池残量／電力\n費用／CO₂");
  setText(presentation, "sh/0buh8zy5", "全便を走れる計画ができた後に\n明細を出して作成する");
  setText(
    presentation,
    "sh/hsvy50re",
    "要点｜見栄えのよい図を先に作らず、車両・電池・電力の明細がそろった結果だけを図にする。",
  );

  setText(presentation, "sh/547mhg3m", "7月17日の計算で分かったこと、まだ分からないこと");
  setFooter(presentation, "sh/na5476l8", 15);
  setText(presentation, "sh/wrm9kvep", "今回の計算から言えること");
  setText(presentation, "sh/upkrilwj", "確認した\n2回");
  setText(presentation, "sh/vqdsrqx4", "→");
  setText(presentation, "sh/4vm9ovel", "計算の成否\nPV入力／候補削減");
  setText(presentation, "sh/it4rm5wv", "問題を見つける証拠\nとして使用");
  setText(presentation, "sh/0z29cbyh", "確認結果");
  setText(presentation, "sh/l0bqlgf2", "割当候補264便\n充電計画は成立せず");
  setText(presentation, "sh/1kjyt83e", "→");
  setText(presentation, "sh/fi1grylo", "正式結果\n担当0便\n未担当264便");
  setText(presentation, "sh/ehsfyt43", "研究用の指標には使わない");
  setText(presentation, "sh/p8jyx83q", "費用・電池残量・電力・CO₂は\nまだ評価しない");
  setText(presentation, "sh/361gvilk", "次の計算で確認すること");
  setText(presentation, "sh/dc3y1s3m", "採用条件\n6項目");
  setText(presentation, "sh/cbuh8nmh", "→");
  setText(presentation, "sh/uh4v2pkj", "全便担当\n違反0\n表示一致");
  setText(presentation, "sh/wj6d4z2p", "正式な基準結果\nとして採用");
  setText(presentation, "sh/ilov6pkv", "時間の細かさ");
  setText(presentation, "sh/jmxwzu1g", "15分を中心に\n30分・60分とも比較");
  setText(presentation, "sh/4n6d8z21", "→");
  setText(presentation, "sh/6p8va9kr", "比較実験\n天候差\n毎時間の見直し");
  setText(presentation, "sh/rqhw3e1c", "同じコード・同じ入力・失敗原因を保存");
  setText(presentation, "sh/f6dcnetg", "運行・電池残量・電力・費用・CO₂の\n先行研究に対応する図を作る");
  setText(
    presentation,
    "sh/18vup4bm",
    "要点｜今回の計算は、効果を示す結果ではなく、どこを直すべきかを示す確認結果として使う。",
  );

  setText(presentation, "sh/8z2h8bq1", "正式な研究結果として採用するための6条件");
  setFooter(presentation, "sh/ip4zel83", 16);
  setText(presentation, "sh/e1sf65o3", "採用条件");
  setText(presentation, "sh/1ojy10ne", "全264便を担当\n充電計画が成立\n別の確認でも違反0");
  setText(presentation, "sh/gnax8v6t", "研究指標を利用可能\n計算の残り幅10%以下\n運行・充電の明細あり");
  setText(presentation, "sh/nqlg3a5k", "7月17日の計算：0／6項目合格");
  setText(
    presentation,
    "sh/ps3y5knq",
    "要点｜6項目をすべて満たすまで、費用・電力・CO₂を『研究成果』として掲載しない。",
  );

  setText(presentation, "sh/1c7e50ni", "修正内容：すべての画面とファイルを同じ判定へそろえる");
  setFooter(presentation, "sh/jilcvq54", 17);
  setText(presentation, "sh/pc7qhwn6", "修正前の食い違い");
  setText(presentation, "sh/29grm1of", "264便 ↔ 0便");
  setText(presentation, "sh/3ap8fm50", "評価不能 ↔ 0円");
  setText(presentation, "sh/gnepkr69", "行った修正\n正式判定を一つに統一\n費用は評価不可／資料作成を停止");
  setText(presentation, "sh/honqdwnu", "現在のコードに採用判定を追加\n7月17日の保存結果は再発防止の確認に使う");
  setText(
    presentation,
    "sh/fm58bm54",
    "要点｜正式判定・集計・研究指標・画面・資料を、すべて同じ『採用できる／できない』へそろえた。",
  );

  setText(presentation, "sh/wrelszu9", "残り2週間：足りない証拠を順番にそろえる");
  setFooter(presentation, "sh/6hw3y9sb", 18);
  setText(presentation, "sh/fapkr6pw", "今、足りないもの");
  setText(
    presentation,
    "sh/upg3i18r",
    "① 走れなかった原因を残す診断記録\n② 15分刻みで264便すべてを走らせた基準結果\n③ 違反ゼロ・費用一致・再現条件の証拠\n④ 毎時間の見直しを24回つないだ確認\n⑤ 太陽光予測の外れ・便のつなぎ候補数の影響",
  );
  setText(presentation, "sh/gbylkbqh", "7月19日～31日の優先順");
  setText(
    presentation,
    "sh/7mpknmp0",
    "【必須｜7月19日～25日】\n● 診断記録を自動保存し、原因を分類\n● 電力会社の電気だけで確認し、条件を一つずつ戻す\n● 15分刻みの基準結果を再現できる形で保存\n\n【次点｜7月26日～31日】\n● 毎時間の見直しを24回つなげる\n● 一日計画との費用・電力・電池残量を比較\n\n【余力】予測の外れ・晴雨・つなぎ候補数を比較",
  );
  setText(
    presentation,
    "sh/to72pw76",
    "要点｜2週間の完了条件は、正式な基準結果を1本作り、毎時間の見直しを24回つないだ1ケースを確認すること。",
  );
}


async function applyImages(presentation) {
  const replacements = [
    ["im/1svqhoje", "01_kpi_truthfulness_gap.png", "正式判定と集計表示の未担当便数比較"],
    ["im/t8z610vu", "02_two_stage_acceptance.png", "担当候補と充電確認後の正式担当便数"],
    ["im/94fuxg7u", "03_solver_gap_runtime.png", "計算の残り幅と実行時間"],
    ["im/jet8va5c", "04_pv_input_profiles.png", "PV発電見込み高低の入力時系列"],
    ["im/zuhs7e58", "05_successor_pruning.png", "便のつなぎ候補を減らす前後の本数"],
    ["im/294fqhsb", "06_output_ledger_completeness.png", "結果明細の行数確認"],
    ["im/7ipgzel8", "07_literature_figure_eligibility.png", "文献対応図の掲載可否"],
    ["im/jy9s7a9k", "08_result_acceptance_gate.png", "正式な修論結果としての受理条件"],
    ["im/r69gv610", "09_source_contract_matrix.png", "正式判定・集計・研究指標の表示比較"],
  ];
  for (const [anchorId, fileName, alt] of replacements) {
    await replaceImage(presentation, anchorId, path.join(FIGURE_DIR, fileName), alt);
  }
}


function applySpeakerNotes(presentation) {
  const sourceRoot = "C:\\master-course\\output\\2026-07-17";
  const auditRoot = "C:\\master-course\\output\\monthly_progress_202607";
  const literatureRoot = "C:\\Users\\RTDS_admin\\iCloudDrive\\Research\\M1&2_電力需要\\先行研究";
  const notes = [
    `話すポイント：専門知識がなくても流れが分かるよう、社会背景から方法、対策、結果、次の課題の順で説明する。\n対象データ：${sourceRoot}\n構成参考：https://note.com/memsblack/n/n85103b886694\n構成参考：https://tadanaohakasenoblog.com/progress-report-template/`,
    `話すポイント：電気バスは、車両だけでなく充電に使う電気まで含めて考える必要がある。\n文献：${literatureRoot}\\修士論文_九蘭_提出版.pdf、都市の太陽光地域余剰電力活用と運行の低炭素化を目的とした電気バス充電計画法の検.pdf。`,
    `話すポイント：時刻表、車両の電池、天候、充電器の台数が互いに影響する。前日計画だけでは当日の変化に対応しにくい。\n文献：${literatureRoot}\\電気バスの低炭素運用に向けたモデル予測型逐次充電計画の導入評価.pdf。`,
    `話すポイント：費用が安いだけでは採用しない。全便運行、電池残量、設備上限、結果表示の一致を同時に確認する。\n研究上の成功条件はスライド16で具体化する。`,
    `話すポイント：本研究は、一日全体の基本計画を作り、毎正時にその日残りの充電計画を更新し、次の1時間だけ実行する。\n『最低限必要な充電量』は時刻や充電器混雑を無視した早期確認値であり、実際の充電実績ではない。\n『朝の営業所蓄電池で使える余分』は終業時目標を超える部分だけ。朝と終業時が同じ300 kWhなら0 kWh。`,
    `話すポイント：一日計画では、時刻表・車両・設備・電池・太陽光予測を入力し、担当車両と充電予定を決める。候補を作った後、実際に走れるかまで確認する。`,
    `話すポイント：毎正時に最新の電池残量と太陽光予測を入れる。担当便は固定し、実行済み区間を二重に数えず、残りの充電だけを見直す。\n先行文献は二日計画の日次更新。本研究はその逐次更新の考え方を一日計画・毎正時更新へ応用しており、時間幅は同一ではない。`,
    `話すポイント：正式判定では264便が未担当なのに、集計では0便と表示された。失敗時は費用を0円とせず、評価不可として資料作成も止める。\n根拠：${sourceRoot}\\run_20260717_0003 と run_20260717_1240。`,
    `話すポイント：最初に264便の担当候補は作れたが、充電器・電池残量まで含めると成立しなかった。候補を正式結果として使わない。\n根拠：正式判定ファイルの候補264便、正式担当0便。`,
    `話すポイント：48.37%は、計算がまだどの程度絞り切れていないかを示す値。目標10%に届いていないので、最もよい計画とは言わない。\n根拠：両runの計算記録。`,
    `話すポイント：太陽光の入力は614.7 kWhと101.1 kWhで異なる。ただし両方とも充電計画が成立していないため、費用や利用量の差は比較しない。\n根拠：${auditRoot}\\run_audit_20260717.csv。`,
    `話すポイント：計算を速くするため、各便の次候補を最大8本に絞った。良い候補を消す可能性があるため、8・16・32・無制限で比較する。\n根拠：便のつなぎ候補678,600本から113,712本へ削減。`,
    `話すポイント：運行、充電、電池残量の明細は0行だった。明細がない場合、0円や0kWhではなく結果なしとして扱う。\n根拠：${auditRoot}\\artifact_row_counts_20260717.csv。`,
    `話すポイント：今回載せられるのは、計算状況、便数の食い違い、太陽光入力の確認図だけ。先行研究にある運行・電池・電力・費用・CO₂図は正式結果後に作る。`,
    `話すポイント：今回の2回は修正箇所を示す確認用データ。毎正時の見直し効果を示す実験結果ではない。入力条件と運用結果を混同しない。`,
    `話すポイント：6条件をすべて満たした場合だけ研究結果として採用する。7月17日の2回は0項目で、費用やCO₂の比較には使わない。`,
    `話すポイント：正式判定、集計、研究指標、画面、資料作成を一つの判定へそろえた。7月17日の保存結果は、同じ不具合が戻らないか確かめるために残す。`,
    `話すポイント：不足しているのは新機能ではなく、結果を信頼するための証拠である。7月19日から25日は、走れない原因を保存し、設備条件を緩めた状態から一つずつ戻して、15分刻み・264便・違反0の正式な基準結果を1本固定する。7月26日から31日は、その割当を使って毎時間の見直しを24回つなぎ、一日計画との違いを比較する。予測誤差、晴雨、便のつなぎ候補数の比較は、この2条件を満たした場合だけ行う。`,
  ];
  notes.forEach((text, index) => setNotes(presentation, index + 1, text));
}


async function main() {
  const args = parseArgs(process.argv.slice(2));
  const workspace = path.resolve(args.workspace ?? DEFAULT_WORKSPACE);
  const starterPptx = path.join(workspace, TEMPLATE_STARTER_NAME);
  const source = path.resolve(args.source ?? starterPptx);
  const output = path.resolve(args.output ?? OUTPUT_PPTX);
  const { FileBlob, PresentationFile } = await importArtifactTool(workspace);
  inheritedAnchorLocators = await buildInheritedAnchorLocators(workspace);
  const presentation = await PresentationFile.importPptx(await FileBlob.load(source));
  applyCoreText(presentation);
  applyEvidenceSlideText(presentation);
  await applyImages(presentation);
  applySpeakerNotes(presentation);
  await fs.mkdir(path.dirname(output), { recursive: true });
  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(output);
  const stat = await fs.stat(output);
  if (stat.size === 0) throw new Error(`empty PPTX export: ${output}`);
  process.stdout.write(`${output}\n${stat.size} bytes\n`);
}


await main();
