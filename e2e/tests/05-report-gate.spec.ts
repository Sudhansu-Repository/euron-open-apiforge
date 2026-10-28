import { expect, test } from "@playwright/test";

import { createProject, CSRF, deleteProjectApi, GATED_SPEC, RUN, waitForSucceeded } from "../helpers";

test("a spec with lint errors needs the report accepted before it generates", async ({ page, request }) => {
  test.setTimeout(150_000);
  let slug: string | undefined;
  try {
    slug = await createProject(page, `E2E Gate ${RUN}`);
    const upload = page.getByRole("dialog", { name: "Upload a spec version" });
    await upload.getByRole("radio", { name: "Paste text" }).click();
    await upload.locator("#spec-filename").fill("gated.yaml");
    await upload.locator("#spec-text").fill(GATED_SPEC);
    await upload.getByRole("button", { name: "Upload and lint" }).click();
    await expect(upload.getByText("Version 1 created")).toBeVisible();
    await expect(upload.getByText("1 error, 0 warnings")).toBeVisible();
    await upload.getByText("Open version 1", { exact: true }).click();

    // The version page explains the error with its code and pointer.
    await expect(page.getByRole("heading", { name: /v1: Gated Devices/ })).toBeVisible();
    await expect(page.getByText("security_scheme_unsupported").first()).toBeVisible();
    await expect(page.getByText("/components/securitySchemes/clientCert").first()).toBeVisible();

    // The API refuses to generate it without an explicit accept.
    const refused = await request.post(`/api/v1/projects/${slug}/generations`, {
      headers: CSRF,
      data: { spec_number: 1, accept_report: false },
    });
    expect(refused.status()).toBeGreaterThanOrEqual(400);
    expect(refused.status()).toBeLessThan(500);

    await page.getByRole("button", { name: "Generate from this version" }).click();
    const dialog = page.getByRole("dialog", { name: "Generate a FastAPI project" });
    await expect(dialog.getByText("Version 1 has 1 error")).toBeVisible();
    await expect(dialog.getByText(/security_scheme_unsupported/)).toBeVisible();
    const go = dialog.getByRole("button", { name: "Generate", exact: true });
    await expect(go).toBeDisabled();
    await dialog.getByLabel("Accept the report and generate without these parts").check();
    await expect(go).toBeEnabled();
    await go.click();

    await expect(page).toHaveURL(new RegExp(`/projects/${slug}/generations/1$`));
    await waitForSucceeded(page);
    const accepted = page.locator("dl > div", { hasText: "Report errors accepted" });
    await expect(accepted.getByText("Yes")).toBeVisible();
  } finally {
    await deleteProjectApi(request, slug);
  }
});
