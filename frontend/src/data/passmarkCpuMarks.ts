/** Public PassMark CPU Mark snapshot for the CPU models in the current cluster.
 * The values are model averages, not measurements of these individual PCs.
 * Source: https://www.cpubenchmark.net/cpu-list/all (2026-09-23).
 */
const CAPTURED_ON = "2026-09-23";

type CpuMarkEntry = {
  pattern: RegExp;
  name: string;
  score: number;
  id: number;
};

const ENTRIES: CpuMarkEntry[] = [
  {
    pattern: /i7-12700(?![a-z0-9])/i,
    name: "Intel Core i7-12700",
    score: 29763,
    id: 4669,
  },
  {
    pattern: /i7-11800H(?![a-z0-9])/i,
    name: "Intel Core i7-11800H @ 2.30GHz",
    score: 19577,
    id: 4358,
  },
  {
    pattern: /i5-8350U(?![a-z0-9])/i,
    name: "Intel Core i5-8350U @ 1.70GHz",
    score: 6081,
    id: 3150,
  },
  {
    pattern: /Ryzen 9 3950X(?![a-z0-9])/i,
    name: "AMD Ryzen 9 3950X",
    score: 38398,
    id: 3598,
  },
  {
    pattern: /i5-8265U(?![a-z0-9])/i,
    name: "Intel Core i5-8265U @ 1.60GHz",
    score: 5770,
    id: 3323,
  },
  {
    pattern: /i7-6700(?![a-z0-9])/i,
    name: "Intel Core i7-6700 @ 3.40GHz",
    score: 8032,
    id: 2598,
  },
  {
    pattern: /i5-8250U(?![a-z0-9])/i,
    name: "Intel Core i5-8250U @ 1.60GHz",
    score: 5777,
    id: 3042,
  },
  {
    pattern: /i7-8550U(?![a-z0-9])/i,
    name: "Intel Core i7-8550U @ 1.80GHz",
    score: 5795,
    id: 3064,
  },
  {
    pattern: /i7-8850H(?![a-z0-9])/i,
    name: "Intel Core i7-8850H @ 2.60GHz",
    score: 10004,
    id: 3247,
  },
  {
    pattern: /Xeon\(R\) W-2123(?![a-z0-9])/i,
    name: "Intel Xeon W-2123 @ 3.60GHz",
    score: 8465,
    id: 3136,
  },
  {
    pattern: /Xeon\(R\) Silver 4108(?![a-z0-9])/i,
    name: "Intel Xeon Silver 4108 @ 1.80GHz",
    score: 9225,
    id: 3167,
  },
  {
    pattern: /Ryzen 7 PRO 3700U(?![a-z0-9])/i,
    name: "AMD Ryzen 7 PRO 3700U",
    score: 7182,
    id: 3433,
  },
  {
    pattern: /i7-7500U(?![a-z0-9])/i,
    name: "Intel Core i7-7500U @ 2.70GHz",
    score: 3636,
    id: 2863,
  },
];

export function passmarkCpuMark(model: string | null | undefined) {
  if (!model) return null;
  const entry = ENTRIES.find(({ pattern }) => pattern.test(model));
  if (!entry) return null;
  return {
    score: entry.score,
    capturedOn: CAPTURED_ON,
    sourceUrl: `https://www.cpubenchmark.net/cpu_lookup.php?cpu=${encodeURIComponent(entry.name)}&id=${entry.id}`,
  };
}
