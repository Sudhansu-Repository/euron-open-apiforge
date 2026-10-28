import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { type APIRequestContext, expect, type Page } from "@playwright/test";

export const OWNER = {
  email: process.env.E2E_EMAIL || "owner@apiforge.local",
  password: process.env.E2E_PASSWORD || process.env.AF_DEMO_PASSWORD || "",
};

/** The API itself, for API-key clients that call it directly instead of through the web origin. */
export const API_URL = (process.env.API_URL || "http://localhost:4630").replace(/\/+$/, "");

/** The web app (it proxies /api/v1 to the API on the same origin). */
export const WEB_URL = (process.env.WEB_URL || "http://localhost:4610").replace(/\/+$/, "");

/** A per-run suffix so suites can run repeatedly against the same demo database. */
export const RUN = process.env.E2E_RUN || Date.now().toString(36).slice(-5);

/** Mutations made with the session cookie need this header (the API's CSRF guard). */
export const CSRF = { "x-apiforge-csrf": "1" };

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** The example specs that ship with the generator. */
export const CORPUS = path.resolve(HERE, "../apps/forge/src/apiforge/corpus");

export function corpusPath(name: string): string {
  return path.join(CORPUS, name);
}

export function corpusText(name: string): string {
  return readFileSync(corpusPath(name), "utf8");
}

/** Pet Store with one more operation and a new version number: an upload with real changes. */
export function petstoreWithPhoto(): string {
  const photo = [
    "  /pets/{petId}/photo:",
    "    get:",
    "      tags: [pets]",
    "      operationId: getPetPhoto",
    "      summary: A pet's photo",
    "      parameters:",
    "        - name: petId",
    "          in: path",
    "          required: true",
    "          schema:",
    "            type: integer",
    "      responses:",
    '        "200":',
    "          description: The photo",
    "",
  ].join("\n");
  const text = corpusText("petstore.yaml").replace("  version: 1.0.0", "  version: 1.1.0");
  const at = text.indexOf("\ncomponents:");
  if (at < 0) throw new Error("petstore.yaml has no components section");
  return `${text.slice(0, at + 1)}${photo}${text.slice(at + 1)}`;
}

/** A valid spec whose lint report has an error: mutual TLS has no FastAPI equivalent. */
export const GATED_SPEC = `openapi: 3.1.0
info:
  title: Gated Devices
  version: 1.0.0
paths:
  /devices:
    get:
      operationId: listDevices
      security:
        - clientCert: []
      responses:
        "200":
          description: Every device
components:
  securitySchemes:
    clientCert:
      type: mutualTLS
`;

/** Open the dashboard with the shared owner session from global setup. */
export async function asOwner(page: Page, path = "/"): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
}

/** Sign in through the real form (for auth tests and other users). */
export async function signIn(page: Page, email = OWNER.email, password = OWNER.password): Promise<void> {
  await page.goto("/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
  await expect(page).not.toHaveURL(/\/login/);
}

/** Pick an option in one of the dashboard's custom selects. */
export async function choose(page: Page, triggerId: string, option: string | RegExp): Promise<void> {
  await page.locator(`#${triggerId}`).click();
  await page.getByRole("option", { name: option }).first().click();
}

/** Create an empty project through the New project dialog; returns its slug. */
export async function createProject(page: Page, name: string, description = ""): Promise<string> {
  await asOwner(page, "/projects");
  await page.getByRole("button", { name: "New project" }).click();
  await page.locator("#np-name").fill(name);
  if (description) await page.locator("#np-desc").fill(description);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/[a-z0-9-]+/);
  const slug = new URL(page.url()).pathname.split("/")[2] ?? "";
  expect(slug).not.toBe("");
  return slug;
}

/** Remove a scratch project with the owner session (cleanup only; journeys stay in the UI). */
export async function deleteProjectApi(request: APIRequestContext, slug: string | undefined): Promise<void> {
  if (!slug) return;
  const resp = await request.delete(`/api/v1/projects/${encodeURIComponent(slug)}`, { headers: CSRF });
  expect([204, 200, 404]).toContain(resp.status());
}

/** Wait on a generation page until the worker has finished it successfully. */
export async function waitForSucceeded(page: Page): Promise<void> {
  const heading = page.getByRole("heading", { level: 1 });
  await expect(heading).toContainText(/Generation #\d+/);
  await expect(heading.getByText("Succeeded")).toBeVisible({ timeout: 90_000 });
}
