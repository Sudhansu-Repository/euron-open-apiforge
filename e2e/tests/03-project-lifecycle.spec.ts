import { expect, type Page, test } from "@playwright/test";

import { corpusPath, createProject, deleteProjectApi, petstoreWithPhoto, RUN } from "../helpers";

function uploadDialog(page: Page) {
  return page.getByRole("dialog", { name: "Upload a spec version" });
}

async function openUpload(page: Page) {
  if (!(await uploadDialog(page).isVisible())) {
    await page.getByRole("button", { name: "Upload spec" }).click();
  }
  await expect(uploadDialog(page)).toBeVisible();
}

test("create a project, upload versions, see reports, changes, duplicates and rejections", async ({ page, request }) => {
  let slug: string | undefined;
  try {
    slug = await createProject(page, `E2E Pets ${RUN}`, "Scratch project from the e2e suite");
    // Right after creating, the upload dialog opens by itself.
    const dialog = uploadDialog(page);
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("Spec file").setInputFiles(corpusPath("petstore.yaml"));
    await expect(dialog.getByText("petstore.yaml")).toBeVisible();
    await expect(page.getByText(`E2E Pets ${RUN}`, { exact: true }).first()).toBeAttached();
    await dialog.locator("#spec-note").fill("First upload");
    await dialog.getByRole("button", { name: "Upload and lint" }).click();
    await expect(dialog.getByText("Version 1 created")).toBeVisible();
    await expect(dialog.getByText("Pet Store 1.0.0")).toBeVisible();
    await dialog.getByText("Open version 1", { exact: true }).click();

    // Version 1: its lint report, operations and the "first version" summary.
    await expect(page).toHaveURL(new RegExp(`/projects/${slug}/specs/1$`));
    await expect(page.getByRole("heading", { name: /v1: Pet Store/ })).toBeVisible();
    await expect(page.getByText("Lint report", { exact: true })).toBeVisible();
    await expect(page.getByText("Clean report")).toBeVisible();
    const ops = page.locator("table").first();
    for (const fn of ["listPets", "createPet", "getPet", "deletePet"]) {
      await expect(ops.getByText(fn).first()).toBeVisible();
    }
    await expect(page.getByText("First version", { exact: true })).toBeVisible();
    await expect(page.getByText("First upload")).toBeVisible();

    // Version 2 adds an operation: the comparison lists it.
    await page.getByRole("link", { name: `E2E Pets ${RUN}` }).click();
    await openUpload(page);
    await dialog.getByLabel("Spec file").setInputFiles({
      name: "petstore.yaml",
      mimeType: "application/yaml",
      buffer: Buffer.from(petstoreWithPhoto()),
    });
    await dialog.getByRole("button", { name: "Upload and lint" }).click();
    await expect(dialog.getByText("Version 2 created")).toBeVisible();
    await dialog.getByText("Open version 2", { exact: true }).click();
    await expect(page.getByRole("heading", { name: /v2: Pet Store/ })).toBeVisible();
    await expect(page.getByText("Changes from version 1")).toBeVisible();
    await expect(page.getByText("1 added")).toBeVisible();
    await expect(page.getByText("/pets/{petId}/photo").first()).toBeVisible();

    // The same bytes again store nothing new.
    await page.getByRole("link", { name: `E2E Pets ${RUN}` }).click();
    await openUpload(page);
    await dialog.getByLabel("Spec file").setInputFiles({
      name: "petstore.yaml",
      mimeType: "application/yaml",
      buffer: Buffer.from(petstoreWithPhoto()),
    });
    await dialog.getByRole("button", { name: "Upload and lint" }).click();
    await expect(dialog.getByText("This exact spec is already version 2")).toBeVisible();
    await dialog.getByRole("button", { name: "Upload another" }).click();

    // An invalid document is rejected with each reason listed (422).
    const rejected = page.waitForResponse((r) => r.url().includes(`/projects/${slug}/specs`) && r.request().method() === "POST");
    await dialog.getByLabel("Spec file").setInputFiles({
      name: "broken.yaml",
      mimeType: "application/yaml",
      buffer: Buffer.from("openapi: 3.1.0\ninfo:\n  title: Broken\npaths:\n  /x:\n    get: 12\n"),
    });
    await dialog.getByRole("button", { name: "Upload and lint" }).click();
    expect((await rejected).status()).toBe(422);
    const panel = dialog.getByRole("alert");
    await expect(panel.getByText("The spec was rejected")).toBeVisible();
    await expect(panel.getByRole("listitem").filter({ hasText: "/info: 'version' is a required property" })).toBeVisible();
    await expect(panel.getByRole("listitem").filter({ hasText: "12 is not of type 'object'" })).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();

    // The version list holds exactly the two stored versions.
    await expect(page.getByText(/2 spec versions/)).toBeVisible();
    await expect(page.getByRole("link", { name: "v2" })).toBeVisible();
    await expect(page.getByRole("link", { name: "v1" })).toBeVisible();
    await expect(page.getByText("Latest")).toBeVisible();
  } finally {
    await deleteProjectApi(request, slug);
  }
});
