import { expect, test } from "@playwright/test";

import { createProject, deleteProjectApi, RUN } from "../helpers";

test("rename a project, change its defaults, and delete it through the confirm dialog", async ({ page, request }) => {
  let slug: string | undefined;
  try {
    slug = await createProject(page, `E2E Settings ${RUN}`);
    await page.getByRole("dialog", { name: "Upload a spec version" }).getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByText("No spec uploaded yet")).toBeVisible();
    await page.getByRole("tab", { name: "Settings" }).click();
    await expect(page).toHaveURL(/\?tab=settings$/);

    const save = page.getByRole("button", { name: "Save changes" });
    await expect(save).toBeDisabled();
    await page.locator("#ps-name").fill(`E2E Renamed ${RUN}`);
    await page.locator("#ps-desc").fill("Renamed by the e2e suite");
    await expect(page.locator("#ps-db")).not.toBeChecked();
    await page.locator(`label[for="ps-db"]`).click();
    await page.locator(`label[for="ps-ci"]`).click();
    await save.click();
    await expect(page.getByText("Project saved.")).toBeVisible();

    // It sticks, and the address does not change.
    await page.reload();
    await expect(page).toHaveURL(new RegExp(`/projects/${slug}\\?tab=settings$`));
    await expect(page.getByRole("heading", { name: `E2E Renamed ${RUN}` })).toBeVisible();
    await expect(page.locator("#ps-name")).toHaveValue(`E2E Renamed ${RUN}`);
    await expect(page.locator("#ps-db")).toBeChecked();
    await expect(page.locator("#ps-ci")).not.toBeChecked();
    await expect(page.locator("#ps-docker")).toBeChecked();

    // Cancelling the confirm keeps it; confirming deletes it.
    await page.getByRole("button", { name: "Delete project" }).click();
    const confirm = page.getByRole("dialog", { name: `Delete "E2E Renamed ${RUN}"?` });
    await expect(confirm.getByText("This cannot be undone.")).toBeVisible();
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(confirm).toHaveCount(0);
    await page.getByRole("button", { name: "Delete project" }).click();
    await confirm.getByRole("button", { name: "Delete project" }).click();
    await expect(page).toHaveURL(/\/projects$/);
    await expect(page.getByText(`Deleted "E2E Renamed ${RUN}".`)).toBeVisible();
    await expect(page.getByRole("link", { name: `E2E Renamed ${RUN}` })).toHaveCount(0);

    await page.goto(`/projects/${slug}`);
    await expect(page.getByText("Project not found")).toBeVisible();
    slug = undefined;
  } finally {
    await deleteProjectApi(request, slug);
  }
});
