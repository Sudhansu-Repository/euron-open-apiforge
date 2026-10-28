/**
 * Curated README screenshots and tour frames from a freshly seeded stack.
 *
 *   make up && make demo
 *   cd scripts/qa && QA_BASE=http://localhost:4610 QA_PASSWORD=... node screenshots.mjs
 *   ../../scripts/qa/make-tour.sh        (stitches the frames into docs/assets/tour.gif)
 *
 * Writes docs/assets/screenshots/NN-name.png and scripts/qa/output/tour/NN.png. Read only:
 * it opens dialogs but never submits them, so the demo data is left as it was.
 */
import { mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.QA_BASE ?? "http://localhost:4610";
const EMAIL = process.env.QA_EMAIL ?? "owner@apiforge.local";
const PASSWORD = process.env.QA_PASSWORD ?? process.env.AF_DEMO_PASSWORD;
if (!PASSWORD) {
  console.error("Set QA_PASSWORD to the demo password (AF_DEMO_PASSWORD in deploy/compose/.env), or run make screenshots.");
  process.exit(1);
}
const SHOTS = path.resolve(HERE, "../../docs/assets/screenshots");
const TOUR = path.resolve(HERE, "output/tour");
const CHROME = process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH) ? process.env.CHROME_PATH : undefined;
const DESKTOP = { width: 1440, height: 900, deviceScaleFactor: 1 };

/** Pet Store has the richest seed: three spec versions and a --db generation. */
const PROJECT = "pet-store";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let tourIndex = 0;

async function settle(page, ms = 1200) {
  await page.waitForNetworkIdle({ idleTime: 400, timeout: 20_000 }).catch(() => {});
  await sleep(ms);
}

async function shot(page, name, { tour = true, fullPage = false } = {}) {
  await page.evaluate(() => window.scrollTo(0, 0));
  // Park the pointer in an empty corner so no hover tooltip leaks into a capture.
  await page.mouse.move(1, 1);
  await sleep(250);
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage });
  if (tour) await page.screenshot({ path: path.join(TOUR, `${String(++tourIndex).padStart(2, "0")}.png`) });
  console.log(`saved ${name}`);
}

async function clickButton(page, text, { exact = false, scope = "body" } = {}) {
  const buttons = await page.$$(`${scope} button, ${scope} [role=button]`);
  for (const b of buttons) {
    const t = ((await b.evaluate((el) => el.textContent)) ?? "").trim();
    if (exact ? t === text : t.includes(text)) {
      await b.click();
      return;
    }
  }
  throw new Error(`button ${text} not found`);
}

async function visit(page, route, ms = 1500) {
  await page.goto(`${BASE}${route}`, { waitUntil: "networkidle2" });
  await page.waitForSelector("main h1", { timeout: 20_000 });
  await page.waitForFunction(() => !document.querySelector("main [data-slot='skeleton'], main [aria-busy='true']"), { timeout: 20_000 });
  await settle(page, ms);
}

/** The newest succeeded generation of the project, and its middle spec version (it has changes). */
async function ids(page) {
  return page.evaluate(async (project) => {
    const specs = await (await fetch(`/api/v1/projects/${project}/specs`)).json();
    const gens = await (await fetch(`/api/v1/projects/${project}/generations`)).json();
    return {
      spec: specs.length >= 3 ? specs[1].number : specs[0].number,
      gen: gens.find((g) => g.status === "succeeded").number,
    };
  }, PROJECT);
}

async function themedPage(ctx, theme, viewport) {
  const page = await ctx.newPage();
  await page.setViewport(viewport);
  await page.evaluateOnNewDocument((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, theme);
  return page;
}

async function main() {
  await mkdir(SHOTS, { recursive: true });
  await mkdir(TOUR, { recursive: true });
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.createBrowserContext();
  const page = await themedPage(ctx, "light", DESKTOP);

  await page.goto(`${BASE}/login`, { waitUntil: "networkidle2" });
  await sleep(600);
  await shot(page, "00-sign-in", { tour: false });
  await page.type("#email", EMAIL);
  await page.type("#password", PASSWORD);
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle2" }), page.click("button[type=submit]")]);

  const { spec, gen } = await ids(page);

  await visit(page, "/", 2000);
  await shot(page, "01-overview");

  await visit(page, "/projects");
  await shot(page, "02-projects");

  await visit(page, `/projects/${PROJECT}`);
  await shot(page, "03-project-specs");

  // A version that changed operations: the comparison lists which parts changed.
  await visit(page, `/projects/${PROJECT}/specs/${spec}`);
  await shot(page, "04-spec-version");

  // The lint report of the example built to show what APIForge approximates.
  await visit(page, "/projects/edge-cases/specs/1");
  await shot(page, "05-lint-report");

  await visit(page, `/projects/${PROJECT}?tab=generations`);
  await shot(page, "06-generations");

  // The generate dialog, opened but not submitted.
  await clickButton(page, "Generate", { exact: true, scope: "main" });
  await page.waitForSelector("[role=dialog] #gen-spec", { timeout: 10_000 });
  await settle(page, 600);
  await shot(page, "07-generate-dialog");
  await page.keyboard.press("Escape");

  await visit(page, `/projects/${PROJECT}/generations/${gen}?file=app/handlers/pets.py`, 2000);
  await shot(page, "08-generation-files");

  await visit(page, `/projects/${PROJECT}/generations/${gen}?file=app/generated/routers/pets.py`, 2000);
  await shot(page, "09-generated-router");

  // Lint the starter spec so the report and the operations are on screen.
  await visit(page, "/playground");
  await clickButton(page, "Lint", { exact: true, scope: "main" });
  await page.waitForFunction(() => [...document.querySelectorAll("main h2")].some((h) => h.textContent?.includes("Operations")), { timeout: 20_000 });
  await settle(page, 800);
  await shot(page, "10-playground");

  await visit(page, "/keys");
  await shot(page, "11-api-keys");

  await visit(page, "/users");
  await shot(page, "12-users");

  await visit(page, "/audit");
  await shot(page, "13-audit-log");

  await visit(page, "/settings");
  await shot(page, "14-settings", { tour: false });

  const dark = await themedPage(ctx, "dark", DESKTOP);
  await visit(dark, `/projects/${PROJECT}/generations/${gen}?file=app/handlers/pets.py`, 2000);
  await shot(dark, "15-dark-mode", { tour: false });

  const phone = await themedPage(ctx, "light", { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await visit(phone, "/", 2000);
  await phone.screenshot({ path: path.join(SHOTS, "16-mobile.png") });
  console.log("saved 16-mobile");

  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
