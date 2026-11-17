// Extra flat icons for the report on the Nishiyama consultation (2026-11-17), same style as ../2026-11-16_nishiyama_consult/make_icons_consult.js.
// Usage: node make_icons_feedback.js  -> icons/*.png (512 px, transparent background)
const path = require("path");
const sharp = require(path.join(process.env.DECK_NODE_MODULES, "sharp"));
const B = "#0485D7", D = "#0268B0", Y = "#F2A900", G = "#7A7A7A", K = "#333333", R = "#D9534F", GR = "#3E9B5F";
const svg = (body) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">${body}</svg>`;
const ICONS = {
  driver: svg(`<circle cx="50" cy="22" r="13" fill="${B}"/><path d="M24 70 A26 26 0 0 1 76 70 Z" fill="${B}"/>
    <circle cx="50" cy="74" r="20" stroke="${K}" stroke-width="6" fill="#fff"/><circle cx="50" cy="74" r="5" fill="${K}"/>
    <path d="M30 74 H45 M55 74 H70 M50 79 V94" stroke="${K}" stroke-width="5"/>`),
  minibus: svg(`<rect x="18" y="30" width="64" height="44" rx="10" fill="${GR}"/><rect x="26" y="38" width="20" height="14" fill="#fff"/><rect x="52" y="38" width="22" height="14" fill="#fff"/>
    <circle cx="34" cy="76" r="8" fill="${K}"/><circle cx="66" cy="76" r="8" fill="${K}"/>`),
  thermo: svg(`<rect x="40" y="10" width="20" height="58" rx="10" fill="#fff" stroke="${K}" stroke-width="5"/><circle cx="50" cy="76" r="16" fill="${R}"/>
    <rect x="45" y="34" width="10" height="40" fill="${R}"/><circle cx="80" cy="24" r="10" fill="${Y}"/>`),
  parcel: svg(`<polygon points="50,10 88,28 50,46 12,28" fill="${Y}"/><polygon points="12,28 50,46 50,92 12,74" fill="#C98C00"/><polygon points="88,28 50,46 50,92 88,74" fill="#E0A000"/>
    <path d="M31 19 L69 37" stroke="#fff" stroke-width="5"/>`),
  ambulance: svg(`<rect x="8" y="34" width="62" height="40" rx="5" fill="#fff" stroke="${K}" stroke-width="5"/><path d="M70 46 H84 L92 60 V74 H70 Z" fill="#fff" stroke="${K}" stroke-width="5"/>
    <rect x="34" y="42" width="10" height="26" fill="${R}"/><rect x="26" y="50" width="26" height="10" fill="${R}"/>
    <circle cx="28" cy="78" r="8" fill="${K}"/><circle cx="76" cy="78" r="8" fill="${K}"/>`),
  atm: svg(`<rect x="16" y="10" width="68" height="82" rx="6" fill="${D}"/><rect x="26" y="20" width="48" height="26" fill="#B8D8F0"/>
    ${[0, 1, 2].map((r) => [0, 1, 2].map((c) => `<rect x="${28 + c * 15}" y="${54 + r * 11}" width="10" height="7" fill="#fff"/>`).join("")).join("")}`),
  building: svg(`<rect x="22" y="10" width="56" height="84" fill="${B}"/>${[0, 1, 2, 3].map((r) => [0, 1, 2].map((c) => `<rect x="${30 + c * 15}" y="${18 + r * 16}" width="9" height="9" fill="#fff"/>`).join("")).join("")}
    <rect x="42" y="78" width="16" height="16" fill="${Y}"/>`),
  talk: svg(`<path d="M8 14 H60 V50 H28 L16 62 V50 H8 Z" fill="${B}"/><path d="M40 40 H92 V76 H84 V88 L72 76 H40 Z" fill="${Y}"/>`),
  check: svg(`<circle cx="42" cy="42" r="28" fill="#fff" stroke="${D}" stroke-width="8"/><path d="M62 62 L88 88" stroke="${D}" stroke-width="10" stroke-linecap="round"/>
    <path d="M30 42 L39 51 L55 34" stroke="${GR}" stroke-width="6" fill="none"/>`),
};
(async () => {
  for (const [n, s] of Object.entries(ICONS)) await sharp(Buffer.from(s)).resize(512, 512).png().toFile(path.join(__dirname, "icons", `${n}.png`));
  console.log("icons:", Object.keys(ICONS).join(", "));
})();
