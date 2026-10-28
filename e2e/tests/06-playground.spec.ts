import { expect, test } from "@playwright/test";

import { asOwner, choose, corpusText, deleteProjectApi, GATED_SPEC, RUN } from "../helpers";

test("lint pasted text, read the report, then create a project from it", async ({ page, request }) => {
  let slug: string | undefined;
  try {
    await asOwner(page, "/playground");
    await expect(page.getByRole("heading", { name: "Playground" })).toBeVisible();
    await expect(page.getByText("Lint to see the report")).toBeVisible();

    await page.locator("#pg-editor").fill(GATED_SPEC);
    await page.locator("#pg-filename").fill("gated.yaml");
    await page.getByRole("button", { name: "Lint", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Gated Devices 1.0.0" })).toBeVisible();
    await expect(page.getByText("1 error", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("security_scheme_unsupported").first()).toBeVisible();
    await expect(page.getByText("listDevices").first()).toBeVisible();

    // Text that is not OpenAPI says why.
    await page.locator("#pg-editor").fill("openapi: 3.1.0\ninfo:\n  title: Broken\npaths: {}\n");
    await page.getByRole("button", { name: "Lint", exact: true }).click();
    await expect(page.getByText("This is not a spec APIForge can read")).toBeVisible();
    await expect(page.getByText(/'version' is a required property/).first()).toBeVisible();

    // A valid spec becomes a project with the editor's text as version 1.
    await page.locator("#pg-editor").fill(corpusText("secure-notes.yaml"));
    await page.getByRole("button", { name: "Lint", exact: true }).click();
    await expect(page.getByRole("heading", { name: /^Secure Notes/ })).toBeVisible();
    await page.getByRole("button", { name: "Create a project from this spec" }).click();
    const dialog = page.getByRole("dialog", { name: "Create a project from this spec" });
    await expect(dialog.locator("#pg-name")).toHaveValue("Secure Notes");
    await dialog.locator("#pg-name").fill(`E2E Playground ${RUN}`);
    await dialog.getByRole("button", { name: "Create project" }).click();
    await expect(page).toHaveURL(/\/projects\/[a-z0-9-]+\/specs\/1$/);
    slug = new URL(page.url()).pathname.split("/")[2];
    await expect(page.getByRole("heading", { name: /v1: Secure Notes/ })).toBeVisible();
  } finally {
    await deleteProjectApi(request, slug);
  }
});

test("the Load menu offers the bundled examples and a project's latest spec", async ({ page }) => {
  await asOwner(page, "/playground");
  await choose(page, "pg-source", "Example: Edge Cases");
  await expect(page.locator("#pg-filename")).toHaveValue("edge-cases.yaml");
  await expect(page.locator("#pg-editor")).toHaveValue(/title: Edge Cases/);
  await page.getByRole("button", { name: "Lint", exact: true }).click();
  await expect(page.getByText(/^\d+ warnings$/).first()).toBeVisible();

  await choose(page, "pg-source", "Bookstore, v2");
  await expect(page.locator("#pg-editor")).toHaveValue(/title: Bookstore/);
});
