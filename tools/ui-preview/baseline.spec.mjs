// P5 — Anh chuan (baseline) cho prototype da duyet.
//
// Hai che do:
//  1) Duyet:   PV_APPROVE=<slug>/v<N> npx playwright test --update-snapshots=all
//     -> chup moi (viewport x phuong an) vao ui-preview/<slug>/v<N>/approved/ + ghi approved.json.
//  2) Doi chieu (mac dinh, chay trong CI): voi moi prototype da co approved/approved.json,
//     chup lai va so voi anh chuan. Prototype da duyet ma bi sua -> FAIL.
//
// Anh chuan chi hop le trong DUNG moi truong da chup (container Playwright ghim version),
// vi font/render khac nhau giua may. Moi truong khac -> test bao loi ro rang, khong so sai.
import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync, existsSync, readdirSync, mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { PINNED_ENV } from "./playwright.config.mjs";

const ROOT = resolve(import.meta.dirname, "../../ui-preview");
const APPROVE = process.env.PV_APPROVE || "";
const ENV = process.env.PV_ENV || "local";
const DEFAULT_VIEWPORTS = [{ name: "mobile", width: 412, height: 915 }];

function prototypes() {
  const out = [];
  for (const slug of readdirSync(ROOT, { withFileTypes: true })) {
    if (!slug.isDirectory() || slug.name.startsWith("_")) continue;
    for (const ver of readdirSync(join(ROOT, slug.name), { withFileTypes: true })) {
      const manifest = join(ROOT, slug.name, ver.name, "prototype.json");
      if (!ver.isDirectory() || !existsSync(manifest)) continue;
      const id = `${slug.name}/${ver.name}`;
      const approvedFile = join(ROOT, id, "approved", "approved.json");
      out.push({ id, manifest: JSON.parse(readFileSync(manifest, "utf8")), approvedFile, approved: existsSync(approvedFile) ? JSON.parse(readFileSync(approvedFile, "utf8")) : null });
    }
  }
  return out;
}

const all = prototypes();
if (APPROVE && !all.some((p) => p.id === APPROVE)) throw new Error(`PV_APPROVE=${APPROVE} khong ton tai (can ui-preview/${APPROVE}/prototype.json)`);
const targets = APPROVE ? all.filter((p) => p.id === APPROVE) : all.filter((p) => p.approved);

if (APPROVE) {
  test.beforeAll(() => {
    if (ENV !== PINNED_ENV) throw new Error(`Chi duoc chup anh chuan trong ${PINNED_ENV} (dang: ${ENV}). Dung workflow "UI preview approve".`);
  });
  test.afterAll(() => {
    const p = targets[0];
    mkdirSync(join(ROOT, p.id, "approved"), { recursive: true });
    const record = {
      prototype: p.id,
      approvedAt: new Date().toISOString(),
      approvedBy: process.env.PV_APPROVED_BY || "unknown",
      sourceCommit: process.env.PV_SOURCE_SHA || "unknown",
      environment: PINNED_ENV,
      viewports: p.manifest.viewports || DEFAULT_VIEWPORTS,
      variants: (p.manifest.variants || []).map((v) => v.id),
      note: "Test giao dien cua code that phai doi chieu voi cac PNG trong thu muc nay.",
    };
    writeFileSync(p.approvedFile, JSON.stringify(record, null, 2) + "\n");
  });
}

for (const p of targets) {
  const viewports = p.manifest.viewports || DEFAULT_VIEWPORTS;
  const variants = (p.manifest.variants || []).map((v) => v.id);
  const cases = variants.length ? variants : [null];

  test.describe(p.id, () => {
    test.beforeEach(() => {
      if (!APPROVE && p.approved.environment !== ENV) {
        throw new Error(`Anh chuan cua ${p.id} chup trong ${p.approved.environment}; moi truong hien tai la ${ENV}. Chay test trong container do (CI job "UI preview baseline").`);
      }
    });
    for (const vp of viewports) {
      for (const variant of cases) {
        const name = `${vp.name}${variant ? "-" + variant : ""}`;
        test(name, async ({ page }) => {
          const errors = [];
          page.on("pageerror", (e) => errors.push(String(e)));
          page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
          await page.setViewportSize({ width: vp.width, height: vp.height });
          await page.goto(`/${p.id}/?pv-capture=1${variant ? "#variant=" + variant : ""}`);
          await page.evaluate(() => document.fonts.ready);
          await expect(page).toHaveScreenshot([...p.id.split("/"), "approved", `${name}.png`], { fullPage: true });
          expect(errors, "console/page error").toEqual([]);
        });
      }
    }
  });
}

if (!targets.length) test("khong co prototype nao da duyet", () => {});
