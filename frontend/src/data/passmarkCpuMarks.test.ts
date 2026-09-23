import { expect, it } from "vitest";
import { passmarkCpuMark } from "./passmarkCpuMarks";

it("maps the observed cluster CPU models without conflating model suffixes", () => {
  const models = [
    "12th Gen Intel(R) Core(TM) i7-12700",
    "11th Gen Intel(R) Core(TM) i7-11800H @ 2.30GHz",
    "Intel(R) Core(TM) i5-8350U CPU @ 1.70GHz",
    "AMD Ryzen 9 3950X 16-Core Processor",
    "Intel(R) Core(TM) i5-8265U CPU @ 1.60GHz",
    "Intel(R) Core(TM) i7-6700 CPU @ 3.40GHz",
    "Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz",
    "Intel(R) Core(TM) i7-8550U CPU @ 1.80GHz",
    "Intel(R) Core(TM) i7-8850H CPU @ 2.60GHz",
    "Intel(R) Xeon(R) W-2123 CPU @ 3.60GHz",
    "Intel(R) Xeon(R) Silver 4108 CPU @ 1.80GHz",
    "AMD Ryzen 7 PRO 3700U w/ Radeon Vega Mobile Gfx",
    "Intel(R) Core(TM) i7-7500U CPU @ 2.70GHz",
  ];
  expect(
    models.map((model) => passmarkCpuMark(model)?.score).every(Boolean),
  ).toBe(true);
  expect(passmarkCpuMark("Intel Core i7-12700K")).toBeNull();
  expect(passmarkCpuMark("unknown CPU")).toBeNull();
});
