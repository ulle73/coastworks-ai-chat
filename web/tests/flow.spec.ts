import { test, expect } from "@playwright/test";

test("URL first, anonymous chat, email only after install", async ({
  page,
}) => {
  let created = false;
  let count = 0;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/previews") {
      created = true;
      return route.fulfill({ json: { id: "demo", state: "queued" } });
    }
    if (path === "/api/bots/demo") {
      count++;
      return route.fulfill({
        json: {
          id: "demo",
          url: "https://company.example",
          state: count <= 2 ? "reading" : "ready",
          quality: { pages: 4 },
          published: false,
        },
      });
    }
    if (path.endsWith("/chat"))
      return route.fulfill({
        json: {
          answer: "Vi hjälper företag med installation.",
          sources: [
            { url: "https://company.example/services", title: "Våra tjänster" },
          ],
        },
      });
    if (path.endsWith("/claim"))
      return route.fulfill({ json: { message: "Skickat" } });
    if (path.endsWith("/installation"))
      return route.fulfill({
        status: 401,
        json: { detail: "Bekräfta din e-post." },
      });
    return route.abort();
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Din hemsida. Din AI-assistent." }),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Din e-post", exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("Företagets webbadress").fill("company.example");
  await page.getByRole("button", { name: "Skapa min assistent" }).click();
  await expect(page.getByText("Vi lär känna ditt företag.")).toBeVisible();
  await expect(page.getByText("Hälsa på din nya assistent.")).toBeVisible({
    timeout: 10000,
  });
  expect(created).toBeTruthy();
  await page.getByLabel("Din fråga").fill("Vad gör ni?");
  await page.getByRole("button", { name: "Skicka fråga" }).click();
  await expect(
    page.getByText("Vi hjälper företag med installation."),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Våra tjänster" }),
  ).toHaveAttribute("href", "https://company.example/services");
  await page.getByRole("button", { name: "Lägg till på min hemsida" }).click();
  await expect(page.getByLabel("Din e-post", { exact: true })).toBeVisible();
  await page
    .getByLabel("Din e-post", { exact: true })
    .fill("owner@example.com");
  await page.getByRole("button", { name: "Skicka min länk" }).click();
  await expect(page.getByText("Kolla din inkorg.")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});

test("one-line widget isolates chat and passes a scoped session into its iframe", async ({
  page,
}) => {
  const bot = "12345678-1234-4234-8234-123456789abc";
  const origin = "http://127.0.0.1:4173";
  const customerOrigin = "http://127.0.0.1:4174";
  await page.route(customerOrigin + "/", (r) =>
    r.fulfill({
      contentType: "text/html",
      body: `<h1>Company</h1><script src="${origin}/widget.js" data-bot="${bot}" defer></script>`,
    }),
  );
  await page.route(`**/api/widget/${bot}/session`, (r) =>
    r.fulfill({
      headers: { "Access-Control-Allow-Origin": customerOrigin },
      json: { token: "scoped-test-token" },
    }),
  );
  await page.route(`**/api/widget/${bot}/chat`, (r) => {
    expect(r.request().headers().authorization).toBe(
      "Bearer scoped-test-token",
    );
    return r.fulfill({
      json: { answer: "Ett svar från företaget.", sources: [] },
    });
  });
  await page.goto(customerOrigin + "/");
  // Closed shadow DOM intentionally hides controls from host DOM selectors; use accessibility snapshot via coordinates.
  await expect(page.locator(`#cw-${bot}`)).toBeAttached();
  const size = page.viewportSize()!;
  await page.mouse.click(size.width - 100, size.height - 45);
  // Playwright cannot pierce a closed root: find the isolated frame by its URL instead.
  await expect
    .poll(() => page.frames().some((f) => f.url().includes(`/embed/${bot}`)))
    .toBeTruthy();
  const chatFrame = page
    .frames()
    .find((f) => f.url().includes(`/embed/${bot}`))!;
  await chatFrame.getByLabel("Din fråga").fill("Hej");
  await chatFrame.getByRole("button", { name: "Skicka fråga" }).click();
  await expect(chatFrame.getByText("Ett svar från företaget.")).toBeVisible();
});

test("failed crawl never exposes chat or installation", async ({ page }) => {
  await page.route("**/api/previews", (r) =>
    r.fulfill({ json: { id: "failed" } }),
  );
  await page.route("**/api/bots/failed", (r) =>
    r.fulfill({
      json: {
        id: "failed",
        url: "https://example.com",
        state: "failed",
        quality: {},
        published: false,
        message: "Vi kunde inte läsa tillräckligt av hemsidan.",
      },
    }),
  );
  await page.goto("/");
  await page.getByLabel("Företagets webbadress").fill("example.com");
  await page.getByRole("button", { name: "Skapa min assistent" }).click();
  await expect(page.getByText("Vi behöver lite hjälp här.")).toBeVisible();
  await expect(page.getByLabel("Din fråga")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Lägg till på min hemsida" }),
  ).toHaveCount(0);
});

test("managed is a saved service inquiry", async ({ page }) => {
  let saved = false;
  await page.route("**/api/managed", (r) => {
    saved = r.request().postDataJSON().message.includes("produktdata");
    return r.fulfill({ json: { message: "Sparad" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Berätta om ditt företag" }).click();
  await page.getByLabel("E-post", { exact: true }).fill("team@example.com");
  await page
    .getByLabel("Företagets hemsida", { exact: true })
    .fill("example.com");
  await page
    .getByLabel("Vad vill ni ha hjälp med?")
    .fill("Vi vill koppla vår produktdata.");
  await page.getByRole("button", { name: "Skicka förfrågan" }).click();
  await expect(page.getByText("Tack, din förfrågan är sparad.")).toBeVisible();
  expect(saved).toBeTruthy();
});
