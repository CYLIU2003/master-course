// Extra flat icons for the Nishiyama consultation deck (2026-11-17), same style as ../2026-11-28_midterm_poster/make_icons.js.
// Usage: node make_icons_consult.js  -> icons/*.png (512 px, transparent background)
const path = require("path");
const sharp = require(path.join(process.env.DECK_NODE_MODULES, "sharp"));
const B = "#0485D7", D = "#0268B0", Y = "#F2A900", G = "#7A7A7A", K = "#333333", GR = "#3E9B5F";
const svg = (body) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">${body}</svg>`;
const ICONS = {
  people: svg(`<circle cx="34" cy="28" r="13" fill="${B}"/><path d="M12 84 A22 26 0 0 1 56 84 Z" fill="${B}"/>
    <circle cx="68" cy="34" r="11" fill="${D}"/><path d="M48 88 A20 24 0 0 1 88 88 Z" fill="${D}"/>`),
  elder: svg(`<circle cx="44" cy="17" r="10" fill="${B}"/><g stroke="${B}" stroke-width="10" stroke-linecap="round" fill="none">
    <path d="M44 31 L38 58"/><path d="M38 58 L30 90"/><path d="M38 58 L52 90"/><path d="M42 38 L62 52"/></g>
    <path d="M62 52 L68 94" stroke="${K}" stroke-width="5" stroke-linecap="round"/>`),
  wheelchair: svg(`<circle cx="40" cy="13" r="9" fill="${B}"/><g stroke="${B}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round" fill="none">
    <path d="M40 26 L40 52 L64 52 L72 78"/><path d="M40 34 L58 40"/></g>
    <circle cx="42" cy="70" r="20" stroke="${K}" stroke-width="6" fill="none"/>`),
  home: svg(`<polygon points="8,50 50,12 92,50" fill="${D}"/><rect x="20" y="46" width="60" height="44" fill="${B}"/><rect x="42" y="62" width="16" height="28" fill="#fff"/>`),
  shop: svg(`<rect x="14" y="40" width="72" height="48" fill="${B}"/><path d="M8 40 L18 14 H82 L92 40 Z" fill="${Y}"/>
    <rect x="24" y="52" width="24" height="20" fill="#fff"/><rect x="56" y="52" width="20" height="36" fill="#fff"/>`),
  clipboard: svg(`<rect x="18" y="14" width="64" height="80" rx="6" fill="${B}"/><rect x="36" y="6" width="28" height="16" rx="3" fill="${K}"/>
    ${[36, 54, 72].map((y) => `<path d="M28 ${y} l5 5 l9 -10" stroke="#fff" stroke-width="4" fill="none"/><rect x="48" y="${y - 2}" width="24" height="5" fill="#fff"/>`).join("")}`),
  moon: svg(`<path d="M60 10 A42 42 0 1 0 90 68 A33 33 0 1 1 60 10 Z" fill="${Y}"/>`),
  calendar: svg(`<rect x="10" y="16" width="80" height="74" rx="7" fill="#fff" stroke="${B}" stroke-width="6"/><rect x="10" y="16" width="80" height="20" rx="5" fill="${B}"/>
    ${[0, 1, 2].map((r) => [0, 1, 2, 3].map((c) => `<rect x="${20 + c * 17}" y="${44 + r * 14}" width="11" height="9" fill="${r === 1 && c === 2 ? Y : "#B8D8F0"}"/>`).join("")).join("")}`),
  plan: svg(`<rect x="8" y="12" width="84" height="76" rx="6" fill="#fff" stroke="${D}" stroke-width="5"/>
    <rect x="18" y="26" width="30" height="10" fill="${B}"/><rect x="54" y="26" width="26" height="10" fill="${Y}"/>
    <rect x="28" y="46" width="40" height="10" fill="${G}"/><rect x="18" y="66" width="22" height="10" fill="${Y}"/><rect x="46" y="66" width="34" height="10" fill="${B}"/>`),
  power: svg(`<rect x="20" y="20" width="60" height="70" rx="8" fill="${GR}"/><polygon points="54,28 36,58 48,58 42,82 66,48 53,48 60,28" fill="#fff"/>`),
};
(async () => {
  for (const [n, s] of Object.entries(ICONS)) await sharp(Buffer.from(s)).resize(512, 512).png().toFile(path.join(__dirname, "icons", `${n}.png`));
  console.log("icons:", Object.keys(ICONS).join(", "));
})();
