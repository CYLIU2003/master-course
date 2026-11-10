// Simple flat icons for the poster's system diagram (Fig. 2), drawn here as SVG and rasterized with sharp.
// Usage: node make_icons.js  -> icons/*.png (512 px, transparent background)
const path = require("path");
const fs = require("fs");
const sharp = require(path.join(process.env.DECK_NODE_MODULES, "sharp"));
const B = "#0485D7", D = "#0268B0", Y = "#F2A900", G = "#7A7A7A", K = "#333333";
const svg = (body) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">${body}</svg>`;
const bus = (fill, badge) => `
  <rect x="6" y="22" width="88" height="52" rx="9" fill="${fill}"/>
  <rect x="12" y="29" width="17" height="17" rx="2" fill="#fff"/><rect x="33" y="29" width="17" height="17" rx="2" fill="#fff"/>
  <rect x="54" y="29" width="17" height="17" rx="2" fill="#fff"/><rect x="75" y="29" width="13" height="30" rx="2" fill="#fff"/>
  <circle cx="26" cy="76" r="9" fill="${K}"/><circle cx="26" cy="76" r="4" fill="#ddd"/>
  <circle cx="74" cy="76" r="9" fill="${K}"/><circle cx="74" cy="76" r="4" fill="#ddd"/>${badge}`;
const ICONS = {
  sun: svg(`<circle cx="50" cy="50" r="19" fill="${Y}"/>` + Array.from({ length: 8 }, (_, i) =>
    `<rect x="47" y="8" width="6" height="16" rx="3" fill="${Y}" transform="rotate(${i * 45} 50 50)"/>`).join("")),
  pv: svg(`<polygon points="14,64 30,26 86,26 70,64" fill="${D}"/>` +
    [0, 1, 2].map((i) => `<line x1="${30 + i * 0 + (i + 1) * 14}" y1="26" x2="${14 + (i + 1) * 14}" y2="64" stroke="#fff" stroke-width="2"/>`).join("") +
    `<line x1="22" y1="45" x2="78" y2="45" stroke="#fff" stroke-width="2"/><rect x="46" y="64" width="6" height="18" fill="${G}"/><rect x="34" y="80" width="30" height="6" rx="2" fill="${G}"/>`),
  grid: svg(`<g stroke="${K}" stroke-width="5" fill="none" stroke-linejoin="round"><path d="M50 8 L30 92 M50 8 L70 92 M24 30 H76 M30 52 H70 M36 30 L64 52 M64 30 L36 52 M34 70 L66 92 M66 70 L34 92 M33 70 H67"/></g>`),
  battery: svg(`<rect x="22" y="18" width="56" height="74" rx="7" fill="${B}"/><rect x="38" y="8" width="24" height="12" rx="3" fill="${B}"/>
    <rect x="30" y="28" width="40" height="14" rx="2" fill="#fff" opacity="0.95"/><rect x="30" y="47" width="40" height="14" rx="2" fill="#fff" opacity="0.95"/>
    <rect x="30" y="66" width="40" height="14" rx="2" fill="#fff" opacity="0.45"/>`),
  charger: svg(`<rect x="22" y="10" width="42" height="80" rx="6" fill="${D}"/><rect x="29" y="18" width="28" height="20" rx="2" fill="#fff"/>
    <polygon points="45,44 34,62 43,62 39,78 52,58 43,58 48,44" fill="${Y}"/>
    <path d="M64 40 C 84 40, 84 70, 74 78" stroke="${K}" stroke-width="5" fill="none"/><rect x="68" y="76" width="14" height="10" rx="2" fill="${K}"/>`),
  ebus: svg(bus(B, `<circle cx="82" cy="18" r="14" fill="#fff"/><polygon points="85,6 74,21 81,21 78,31 90,15 83,15" fill="${Y}"/>`)),
  dbus: svg(bus(G, `<path d="M82 4 C 88 14, 94 20, 94 26 a12 12 0 0 1 -24 0 C 70 20, 76 14, 82 4 Z" fill="${K}"/>`)),
};
(async () => {
  for (const [n, s] of Object.entries(ICONS)) {
    await sharp(Buffer.from(s)).resize(512, 512).png().toFile(path.join(__dirname, "icons", `${n}.png`));
  }
  console.log("icons:", Object.keys(ICONS).join(", "));
})();
