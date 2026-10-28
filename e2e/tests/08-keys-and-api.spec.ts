import { expect, test } from "@playwright/test";

import { API_URL, asOwner, RUN } from "../helpers";

test("a read-only API key lists generations and downloads archives, cannot change anything, and dies when revoked", async ({ page, playwright }) => {
  const name = `e2e-${RUN}`;
  await asOwner(page, "/keys");
  await page.getByRole("button", { name: "New key" }).click();
  await page.locator("#key-name").fill(name);
  await page.getByRole("button", { name: "Create key" }).click();
  const key = (await page.getByTestId("new-key").textContent())?.trim() ?? "";
  expect(key).toMatch(/^afk_/);
  await page.getByRole("button", { name: "I have copied the key" }).click();
  await expect(page.locator("tr", { hasText: name })).toBeVisible();

  // Straight to the API: no dashboard cookie, only the key.
  const api = await playwright.request.newContext({ baseURL: API_URL, storageState: { cookies: [], origins: [] } });
  try {
    const auth = { authorization: `Bearer ${key}` };
    const gens = await api.get("/api/v1/projects/pet-store/generations", { headers: auth });
    expect(gens.status()).toBe(200);
    const list = (await gens.json()) as { number: number; status: string }[];
    const done = list.find((g) => g.status === "succeeded");
    expect(done).toBeTruthy();

    const zip = await api.get(`/api/v1/projects/pet-store/generations/${done!.number}/archive`, { headers: auth });
    expect(zip.status()).toBe(200);
    expect(zip.headers()["content-type"]).toContain("application/zip");
    expect((await zip.body()).subarray(0, 2).toString("latin1")).toBe("PK");

    const write = await api.post("/api/v1/projects", { headers: auth, data: { name: `Key write ${RUN}` } });
    expect(write.status()).toBe(403);
    expect((await write.json()).error.code).toBe("read_only_key");

    await page.locator("tr", { hasText: name }).getByRole("button", { name: `Revoke ${name}` }).click();
    await page.getByRole("button", { name: "Revoke key" }).click();
    await expect(page.getByText("Key revoked.")).toBeVisible();
    await expect(page.locator("tr", { hasText: name })).toHaveCount(0);
    expect((await api.get("/api/v1/projects/pet-store/generations", { headers: auth })).status()).toBe(401);
  } finally {
    await api.dispose();
  }
});
