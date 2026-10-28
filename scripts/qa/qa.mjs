/**
 * Browser QA (make qa): signs in through the real form, visits every page of the web app in
 * light and dark at desktop and phone width (as the owner, and as the viewer on pages that
 * differ by role), saves screenshots, and fails on console errors, failed or 4xx/5xx
 * requests, broken images, error states, empty unexplained states, horizontal overflow and
 * tables wider than their panel.
 *
 *   make qa
 *   QA_BASE=http://localhost:4610 QA_OUT=./output node qa.mjs
 *   QA_PAGES=/,/projects QA_THEMES=dark QA_SIZES=desktop QA_ROLES=owner node qa.mjs
 *
 * Uses Puppeteer's bundled Chromium; set CHROME_PATH to use a local browser instead.
 */
import { mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const BASE = process.env.QA_BASE ?? "http://localhost:4610";
const OUT = process.env.QA_OUT ?? path.resolve("output");
const PASSWORD = process.env.QA_PASSWORD ?? process.env.AF_DEMO_PASSWORD ?? "";
const CHROME = process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH) ? process.env.CHROME_PATH : undefined;
if (!PASSWORD) {
  console.error("Set QA_PASSWORD to the demo password (AF_DEMO_PASSWORD in deploy/compose/.env), or run make qa.");
  process.exit(1);
}

/** The seeded project with the richest history: three spec versions and a --db generation. */
const PROJECT = process.env.QA_PROJECT ?? "pet-store";

const ROLES = {
  owner: { email: process.env.QA_EMAIL ?? "owner@apiforge.local" },
  viewer: { email: process.env.QA_VIEWER_EMAIL ?? "viewer@apiforge.local" },
};

// :project, :spec and :gen are filled from the API once signed in.
const ALL_PAGES = [
  "/login",
  "/",
  "/projects",
  "/projects/:project",
  "/projects/:project?tab=generations",
  "/projects/:project?tab=settings",
  "/projects/:project/specs/:spec",
  "/projects/edge-cases/specs/1",
  "/projects/:project/generations/:gen?file=app/handlers/pets.py",
  "/playground",
  "/keys",
  "/users",
  "/audit",
  "/settings",
];
/** Pages whose content changes for a viewer (no write actions, or "Admins only"). */
const VIEWER_PAGES = new Set([
  "/projects",
  "/projects/:project",
  "/projects/:project?tab=settings",
  "/projects/:project/specs/:spec",
  "/projects/:project/generations/:gen?file=app/handlers/pets.py",
  "/playground",
  "/keys",
  "/users",
  "/audit",
]);
const PAGES = process.env.QA_PAGES ? process.env.QA_PAGES.split(",") : ALL_PAGES;
const THEMES = (process.env.QA_THEMES ?? "light,dark").split(",");
const SIZES = {
  desktop: { width: 1440, height: 900 },
  phone: { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
};
const SIZE_KEYS = (process.env.QA_SIZES ?? "desktop,phone").split(",");
const ROLE_KEYS = (process.env.QA_ROLES ?? "owner,viewer").split(",");
const FULL = process.env.QA_FULL !== "0";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function slug(p) {
  if (p === "/") return "overview";
  return p
    .replace(/^\//, "")
    .replace(/\?file=.*$/, "")
    .replace(/[/:?=]/g, "-");
}

/** The spec version and generation to show: the latest of each for the chosen project. */
async function resolveIds(page) {
  return page.evaluate(async (project) => {
    const specs = await (await fetch(`/api/v1/projects/${project}/specs`)).json();
    const gens = await (await fetch(`/api/v1/projects/${project}/generations`)).json();
    // The middle version of a three-version history has changed operations to show.
    const spec = specs.length >= 3 ? specs[1].number : (specs[0]?.number ?? 1);
    const gen = gens.find((g) => g.status === "succeeded")?.number ?? 1;
    return { spec, gen };
  }, PROJECT);
}

/** Lint the starter spec so the playground shows a report, not its empty state. */
async function lintPlayground(page) {
  const buttons = await page.$$("main button");
  for (const b of buttons) {
    const t = ((await b.evaluate((el) => el.textContent)) ?? "").trim();
    if (t === "Lint") {
      await b.click();
      break;
    }
  }
  await page.waitForFunction(() => [...document.querySelectorAll("main h2")].some((h) => h.textContent?.includes("Operations")), {
    timeout: 20_000,
  });
}

/** Empty containers or tables that say nothing: every empty view must explain itself. */
async function emptyStates(page) {
  return page.evaluate(() => {
    const out = [];
    const main = document.querySelector("main");
    if (!main) return ["no main landmark"];
    if ((main.innerText ?? "").trim().length < 60) out.push("main has almost no text");
    for (const body of main.querySelectorAll("table tbody")) {
      if (!body.querySelector("tr")) out.push("a table with no rows");
    }
    for (const s of main.querySelectorAll("section.surface")) {
      if (!(s.innerText ?? "").trim() && !s.querySelector("svg, img, canvas, pre, textarea")) out.push("an empty panel");
    }
    // An EmptyState must say what this is (h3) and why (a paragraph next to it).
    for (const h of main.querySelectorAll("h3")) {
      const box = h.parentElement;
      if (box?.classList.contains("text-center") && !box.querySelector("p")?.textContent?.trim()) {
        out.push(`empty state without an explanation: ${h.textContent}`);
      }
    }
    return out;
  });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
  const problems = [];
  let ids = null;

  for (const role of ROLE_KEYS) {
    const pages = role === "owner" ? PAGES : PAGES.filter((p) => VIEWER_PAGES.has(p));
    if (!pages.length) continue;
    for (const theme of THEMES) {
      for (const sizeKey of SIZE_KEYS) {
        const ctx = await browser.createBrowserContext();
        const page = await ctx.newPage();
        await page.setViewport(SIZES[sizeKey]);
        await page.evaluateOnNewDocument((t) => {
          try {
            localStorage.setItem("theme", t);
          } catch {}
        }, theme);
        const consoleErrors = [];
        page.on("console", (m) => {
          if (m.type() === "error") consoleErrors.push(m.text());
        });
        page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
        page.on("requestfailed", (r) => {
          const err = r.failure()?.errorText ?? "";
          if (!err.includes("ERR_ABORTED")) consoleErrors.push(`requestfailed ${r.url()} ${err}`);
        });
        page.on("response", (r) => {
          if (r.status() >= 400) consoleErrors.push(`HTTP ${r.status()} ${r.url()}`);
        });

        // Sign in through the real form once per context.
        await page.goto(`${BASE}/login`, { waitUntil: "networkidle2" });
        if (role === "owner" && pages.includes("/login")) {
          await sleep(400);
          await page.screenshot({ path: path.join(OUT, `${role}-${sizeKey}-${theme}-login.png`) });
        }
        await page.type("#email", ROLES[role].email);
        await page.type("#password", PASSWORD);
        await Promise.all([page.waitForNavigation({ waitUntil: "networkidle2" }), page.click("button[type=submit]")]);
        if (new URL(page.url()).pathname === "/login") throw new Error(`sign-in as ${ROLES[role].email} failed`);

        if (!ids) ids = await resolveIds(page);

        for (const p of pages) {
          if (p === "/login") continue;
          const url = p.replace(":project", PROJECT).replace(":spec", String(ids.spec)).replace(":gen", String(ids.gen));
          consoleErrors.length = 0;
          await page.goto(`${BASE}${url}`, { waitUntil: "networkidle2", timeout: 45_000 });
          // The page is ready when its heading shows and no skeleton is left.
          await page
            .waitForFunction(
              () => document.querySelector("main h1") && !document.querySelector("main [data-slot='skeleton'], main [aria-busy='true']"),
              { timeout: 30_000 },
            )
            .catch(() => consoleErrors.push("page did not finish loading within 30 s"));
          if (p === "/playground") await lintPlayground(page).catch(() => consoleErrors.push("the playground lint did not show a report"));
          await sleep(600);
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
          const broken = await page.evaluate(() =>
            [...document.images].filter((img) => img.complete && img.naturalWidth === 0).map((img) => img.src),
          );
          // A healthy page with demo data renders no error states.
          const errorStates = await page.evaluate(() =>
            [...document.querySelectorAll("[data-qa='error-state']")].map((el) => el.textContent?.slice(0, 80) ?? ""),
          );
          const empty = await emptyStates(page);
          // A table wider than its panel hides columns behind a sideways scroll nobody sees.
          const clipped = await page.evaluate(() =>
            [...document.querySelectorAll("main [data-slot='table-container']")]
              .filter((el) => el.scrollWidth - el.clientWidth > 1)
              .map((el) => `${el.scrollWidth - el.clientWidth}px`),
          );
          const file = path.join(OUT, `${role}-${sizeKey}-${theme}-${slug(p)}.png`);
          await page.mouse.move(0, 0);
          await page.screenshot({ path: file, fullPage: FULL });
          const issues = [...consoleErrors];
          if (overflow > 1) issues.push(`horizontal overflow ${overflow}px`);
          for (const src of broken) issues.push(`broken image ${src}`);
          for (const text of errorStates) issues.push(`error state: ${text}`);
          for (const text of empty) issues.push(`empty state: ${text}`);
          for (const px of clipped) issues.push(`table scrolls sideways by ${px}`);
          if (issues.length) problems.push({ page: p, role, theme, size: sizeKey, issues });
          console.log(`${issues.length ? "WARN" : "ok  "} ${role} ${sizeKey} ${theme} ${p}${issues.length ? `: ${issues.join(" | ")}` : ""}`);
        }
        await ctx.close();
      }
    }
  }
  await browser.close();
  console.log(`\n${problems.length} page(s) with problems. Screenshots in ${OUT}`);
  if (problems.length) process.exitCode = 1;
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
