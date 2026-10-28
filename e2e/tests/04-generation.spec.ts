import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

import { corpusPath, createProject, deleteProjectApi, RUN, waitForSucceeded } from "../helpers";

test("queue a generation, watch it succeed, browse its files and download the zip", async ({ page, request }) => {
  test.setTimeout(150_000);
  let slug: string | undefined;
  try {
    slug = await createProject(page, `E2E Forge ${RUN}`);
    const upload = page.getByRole("dialog", { name: "Upload a spec version" });
    await upload.getByLabel("Spec file").setInputFiles(corpusPath("petstore.yaml"));
    await upload.getByRole("button", { name: "Upload and lint" }).click();
    await expect(upload.getByText("Version 1 created")).toBeVisible();
    await upload.getByRole("button", { name: "Generate from it" }).click();

    const dialog = page.getByRole("dialog", { name: "Generate a FastAPI project" });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("#gen-spec")).toContainText("v1: Pet Store 1.0.0 (latest)");
    // Clean report: nothing to accept, Generate is ready.
    await expect(dialog.getByText(/Accept the report/)).toHaveCount(0);
    await dialog.getByRole("button", { name: "Generate", exact: true }).click();

    await expect(page).toHaveURL(new RegExp(`/projects/${slug}/generations/1$`));
    await waitForSucceeded(page);

    // The file tree, with the first handler you own opened by default.
    const tree = page.getByRole("tree", { name: "Generated files" });
    await expect(tree).toBeVisible();
    await expect(page.getByText(/created once, never overwritten/)).toBeVisible();
    await expect(page.getByText("app/handlers/pets.py").first()).toBeVisible();
    await expect(page.locator("pre").first()).toContainText("def ");

    // Open another file, then come back to the handler through the tree.
    await tree.locator('button[title^="app/main.py,"]').click();
    await expect(page).toHaveURL(/file=app%2Fmain\.py/);
    await expect(page.getByText("app/main.py").first()).toBeVisible();
    await tree.locator('button[title^="app/handlers/pets.py,"]').click();
    await expect(page).toHaveURL(/file=app%2Fhandlers%2Fpets\.py/);
    await expect(page.locator("pre").first()).toContainText(/list_pets/);

    // Download through the button: a real zip.
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("link", { name: "Download zip" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.zip$/);
    const bytes = await readFile((await download.path())!);
    expect(bytes.subarray(0, 2).toString("latin1")).toBe("PK");

    // The archive is immutable: two downloads match, and the ETag is its sha256.
    const url = `/api/v1/projects/${slug}/generations/1/archive`;
    const first = await request.get(url);
    const second = await request.get(url);
    expect(first.status()).toBe(200);
    expect(second.status()).toBe(200);
    const etag = first.headers()["etag"];
    expect(etag).toBeTruthy();
    expect(second.headers()["etag"]).toBe(etag);
    const a = createHash("sha256").update(await first.body()).digest("hex");
    const b = createHash("sha256").update(await second.body()).digest("hex");
    expect(a).toBe(b);
    expect(etag).toBe(`"${a}"`);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(a);
    const cached = await request.get(url, { headers: { "if-none-match": etag! } });
    expect(cached.status()).toBe(304);

    // The generations tab lists it as succeeded.
    await page.getByRole("link", { name: `E2E Forge ${RUN}` }).click();
    await page.getByRole("tab", { name: "Generations" }).click();
    await expect(page.getByRole("link", { name: "#1" })).toBeVisible();
    await expect(page.getByRole("tabpanel").getByText("Succeeded")).toBeVisible();
  } finally {
    await deleteProjectApi(request, slug);
  }
});
