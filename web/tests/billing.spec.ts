import { test, expect } from "@playwright/test";

test("billing return never unlocks installation until server confirms payment", async ({
  page,
}) => {
  let paid = false;
  let portal = false;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/installation"))
      return route.fulfill({
        json: {
          code: '<script src="https://example.com/widget.js"></script>',
          published: false,
        },
      });
    if (path.endsWith("/billing/refresh") || path.endsWith("/billing"))
      return route.fulfill({
        json: {
          enabled: true,
          active: paid,
          status: paid ? "active" : "none",
          tax_behavior: "inclusive",
          paid_until: null,
          cancel_at_period_end: false,
          can_manage: paid,
        },
      });
    if (path.endsWith("/billing/portal")) {
      portal = true;
      return route.fulfill({
        json: { url: "https://billing.stripe.com/test-portal" },
      });
    }
    if (path.endsWith("/publish"))
      return route.fulfill({ json: { published: true } });
    if (path === "/api/bots/demo")
      return route.fulfill({
        json: {
          id: "demo",
          state: "ready",
          url: "https://company.example",
          quality: { pages: 4 },
          published: false,
        },
      });
    return route.abort();
  });
  await page.goto("/?billing=return&bot=demo");
  await expect(
    page.getByRole("heading", { name: "En chatbot · 399 kr/månad" }),
  ).toBeVisible();
  const publish = page.getByRole("button", { name: "Jag har lagt in koden" });
  await expect(publish).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Fortsätt till betalning · 399 kr/mån" }),
  ).toBeVisible();
  paid = true;
  await page.getByRole("button", { name: "Kontrollera betalningen" }).click();
  await expect(publish).toBeEnabled();
  await publish.click();
  await expect(
    page.getByRole("button", { name: "Installationen är bekräftad" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Hantera abonnemang" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.route("https://billing.stripe.com/**", (r) =>
    r.fulfill({ body: "Portal" }),
  );
  await page.getByRole("button", { name: "Hantera abonnemang" }).click();
  await expect(page).toHaveURL("https://billing.stripe.com/test-portal");
  expect(portal).toBeTruthy();
});
