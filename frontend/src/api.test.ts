import { afterEach, expect, it, vi } from "vitest";
import { api, display, gate } from "./api";

afterEach(() => vi.unstubAllGlobals());
it("keeps unknown, zero, physical validity and research acceptance distinct", () => {
  expect(display(null)).toBe("未確認");
  expect(display(0)).toBe("0");
  expect(gate("OPTIMAL")).toBe("OPTIMAL");
  expect(gate("NOT_REQUESTED")).toBe("NOT_REQUESTED");
  expect(gate("REJECTED")).toBe("未達");
  expect(gate("VALID")).toBe("確認済み");
});
it("surfaces stale prepared-input contract errors without submitting another run", async () => {
  const fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        detail: { code: "STALE_PREPARED_INPUT", message: "Prepare again" },
      }),
      { status: 409 },
    ),
  );
  vi.stubGlobal("fetch", fetch);
  await expect(
    api("/scenarios/x/run-optimization", { method: "POST" }),
  ).rejects.toThrow("STALE_PREPARED_INPUT");
  expect(fetch).toHaveBeenCalledTimes(1);
});
