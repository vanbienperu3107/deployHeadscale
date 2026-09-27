import { defineConfig } from "@playwright/test";

export const PINNED_ENV = "mcr.microsoft.com/playwright:v1.63.0-noble";

export default defineConfig({
  testDir: ".",
  testMatch: "baseline.spec.mjs",
  // Anh chuan nam canh prototype: ui-preview/<slug>/v<N>/approved/<viewport>-<variant>.png
  snapshotPathTemplate: "../../ui-preview/{arg}{ext}",
  fullyParallel: true,
  reporter: [["list"]],
  expect: {
    // Baseline va lan so deu chay trong CUNG container ghim version -> render tat dinh.
    // Nguong tuyet doi nho: doi 1 chu cung phai FAIL (ratio 0.2% tung de lot ~900px).
    toHaveScreenshot: { maxDiffPixels: 10, threshold: 0.1, animations: "disabled", caret: "hide", scale: "css" },
  },
  use: { baseURL: "http://127.0.0.1:4173", browserName: "chromium" },
  webServer: { command: "node serve.mjs", url: "http://127.0.0.1:4173/", reuseExistingServer: false },
});
