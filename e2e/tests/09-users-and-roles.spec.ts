import { expect, test } from "@playwright/test";

import { asOwner, RUN, signIn } from "../helpers";

test("an owner adds a viewer, who reads everything but changes nothing", async ({ page, browser }) => {
  const name = `Val ${RUN}`;
  const email = `val-${RUN}@example.test`;
  const password = "Val-Viewer-12345";

  await asOwner(page, "/users");
  await page.getByRole("button", { name: "Add user" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a user" });
  await dialog.locator("#u-name").fill(name);
  await dialog.locator("#u-email").fill(email);
  await expect(dialog.locator("#u-role")).toContainText("Viewer");
  await dialog.locator("#u-pw").fill(password);
  await dialog.getByRole("button", { name: "Add user" }).click();
  await expect(page.getByText(`${name} can now sign in.`, { exact: false })).toBeVisible();
  const row = page.locator("tr", { hasText: email });
  await expect(row).toBeVisible();

  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const viewer = await ctx.newPage();
  try {
    await signIn(viewer, email, password);
    const nav = viewer.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Projects" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Playground" })).toBeVisible();
    for (const hidden of ["API keys", "Users", "Audit log"]) {
      await expect(nav.getByRole("link", { name: hidden })).toHaveCount(0);
    }

    await viewer.goto("/projects");
    await expect(viewer.getByRole("link", { name: "Pet Store", exact: true })).toBeVisible();
    await expect(viewer.getByRole("button", { name: "New project" })).toHaveCount(0);
    await expect(viewer.getByRole("button", { name: "Start from an example" })).toHaveCount(0);
    await expect(viewer.getByText(/You have read access/)).toBeVisible();

    await viewer.goto("/projects/pet-store");
    await expect(viewer.getByRole("heading", { name: "Pet Store" })).toBeVisible();
    await expect(viewer.getByRole("link", { name: "v3" })).toBeVisible();
    await expect(viewer.getByRole("button", { name: "Upload spec" })).toHaveCount(0);
    await expect(viewer.getByRole("button", { name: "Generate" })).toHaveCount(0);
    await viewer.getByRole("tab", { name: "Settings" }).click();
    await expect(viewer.getByText("Read only: owners and admins change projects.")).toBeVisible();
    await expect(viewer.getByRole("button", { name: "Delete project" })).toBeDisabled();

    await viewer.goto("/projects/pet-store/specs/3");
    await expect(viewer.getByRole("heading", { name: /v3: Pet Store/ })).toBeVisible();
    await expect(viewer.getByRole("button", { name: "Generate from this version" })).toHaveCount(0);

    await viewer.goto("/projects/pet-store/generations/1");
    await expect(viewer.getByRole("heading", { name: /Generation #1/ })).toBeVisible();
    await expect(viewer.getByRole("link", { name: "Download zip" })).toBeVisible();
    await expect(viewer.getByRole("button", { name: "Generate again" })).toHaveCount(0);

    await viewer.goto("/playground");
    await expect(viewer.getByRole("button", { name: "Create a project from this spec" })).toBeDisabled();

    for (const path of ["/users", "/audit", "/keys"]) {
      await viewer.goto(path);
      await expect(viewer.getByText("Admins only")).toBeVisible();
    }
  } finally {
    await ctx.close();
  }

  // Cleanup: users cannot be deleted, so the scratch viewer is disabled.
  await page.reload();
  await row.getByRole("switch", { name: `Disable ${name}` }).click();
  await expect(page.getByText(`${name} was signed out and disabled.`)).toBeVisible();
});

test("the audit log records project and spec changes", async ({ page }) => {
  await asOwner(page, "/audit");
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
  const filter = page.getByLabel("Filter by action");
  for (const action of ["project.created", "spec.uploaded", "generation.queued", "project.deleted"]) {
    await filter.fill(action);
    await expect(page.locator("tbody tr").first().getByText(action, { exact: true })).toBeVisible();
    await expect(page.locator("tbody tr").filter({ hasNotText: action })).toHaveCount(0);
  }
  await filter.fill("no.such.action");
  await expect(page.getByText("No entries for this action")).toBeVisible();
  await page.getByRole("button", { name: "Clear filter" }).click();
  await expect(filter).toHaveValue("");
});

test("the theme switches and the choice sticks", async ({ page }) => {
  await asOwner(page, "/settings");
  const html = page.locator("html");
  await page.getByRole("radiogroup", { name: "Theme" }).getByRole("radio", { name: /dark/i }).click();
  await expect(html).toHaveClass(/dark/);
  await page.reload();
  await expect(html).toHaveClass(/dark/);
  await page.goto("/projects");
  await expect(html).toHaveClass(/dark/);
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(html).not.toHaveClass(/dark/);
  await page.reload();
  await expect(html).not.toHaveClass(/dark/);
});
