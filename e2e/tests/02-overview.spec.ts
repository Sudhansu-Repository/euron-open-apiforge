import { expect, test } from "@playwright/test";

import { asOwner, deleteProjectApi } from "../helpers";

test("the overview shows the seeded projects, generations and spec changes", async ({ page }) => {
  await asOwner(page, "/");
  await expect(page.getByRole("heading", { name: /^Welcome back, Priya/ })).toBeVisible();
  for (const label of ["Projects", "Operations described", "Generations, 7 days", "Median generation time", "Queued now"]) {
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
  }
  await expect(page.getByText("Recent generations")).toBeVisible();
  await expect(page.getByRole("link", { name: "pet-store" }).first()).toBeVisible();
  await expect(page.getByText("Recent spec changes")).toBeVisible();
  await expect(page.getByRole("link", { name: /Pet Store v3/ })).toBeVisible();

  // A recent spec change opens that version.
  await page.getByRole("link", { name: /Pet Store v3/ }).click();
  await expect(page).toHaveURL(/\/projects\/pet-store\/specs\/3$/);
  await expect(page.getByRole("heading", { name: /v3: Pet Store/ })).toBeVisible();
});

test("the projects list shows every seeded project", async ({ page }) => {
  await asOwner(page, "/projects");
  for (const name of ["Pet Store", "Bookstore", "Warehouse Inventory", "Secure Notes", "Edge Cases"]) {
    await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
  }
});

test("starting from a bundled example creates a project with its spec as version 1", async ({ page, request }) => {
  let slug: string | undefined;
  try {
    await asOwner(page, "/projects");
    await page.getByRole("button", { name: "Start from an example" }).click();
    const dialog = page.getByRole("dialog", { name: "Start from an example" });
    for (const title of ["Pet Store", "Bookstore", "Warehouse Inventory", "Secure Notes", "Edge Cases"]) {
      await expect(dialog.getByText(title, { exact: true })).toBeVisible();
    }
    const card = dialog.locator("div.rounded-xl", { hasText: "Edge Cases" }).first();
    await card.getByRole("button", { name: "Use this" }).click();
    await expect(page).toHaveURL(/\/projects\/edge-cases-[a-z0-9-]+$/);
    slug = new URL(page.url()).pathname.split("/")[2];
    await expect(page.getByText(/1 spec version/)).toBeVisible();
    await expect(page.getByRole("link", { name: "v1" })).toBeVisible();
    await expect(page.getByText("From the bundled example")).toBeVisible();

    // A project nobody generated from yet explains what a generation is and offers one.
    await page.getByRole("tab", { name: "Generations" }).click();
    await expect(page.getByText("Nothing generated yet")).toBeVisible();
    await expect(page.getByRole("tabpanel").getByRole("button", { name: "Generate" })).toBeVisible();
  } finally {
    await deleteProjectApi(request, slug);
  }
});
