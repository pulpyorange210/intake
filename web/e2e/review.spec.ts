import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { DATA_DIR } from "../playwright.config";

const FIXTURES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "synthetic_order_form_dataset_50", "pdfs");
const fixture = (name: string) => path.join(FIXTURES, `${name}.pdf`);

async function uploadViaApi(request: APIRequestContext, name: string): Promise<number> {
  const response = await request.post("/api/forms?wait=true", {
    multipart: { file: { name: `${name}.pdf`, mimeType: "application/pdf", buffer: readFileSync(fixture(name)) } },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).form_id;
}

async function openForm(page: Page, id: number) {
  await page.goto(`/forms/${id}`);
  await expect(page.getByTestId("item-row").first()).toBeVisible();
  await expect(page.locator(".react-pdf__Page__textContent")).toBeVisible();
}

/** The sheet the CSV client writes when no Google credentials are set: what the "Sheets client" received. */
function sheetRows(): string[][] {
  const file = path.join(DATA_DIR, "sheet.csv");
  if (!existsSync(file)) return [];
  return readFileSync(file, "utf8").trim().split(/\r?\n/).slice(1).map((line) => line.split(","));
}

// of-0003 is a clean form (no flags), so it can be approved as soon as it is reviewed.
test("upload a form, edit one value, approve: the sheet receives the edited value", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("upload-input").setInputFiles(fixture("of-0003"));
  const row = page.getByTestId("queue-row").filter({ hasText: "of-0003.pdf" });
  await expect(row).toBeVisible();
  await expect(row).not.toContainText("extracting", { timeout: 20_000 });
  await row.click();

  const item = page.getByTestId("item-row").first();
  await expect(item).toBeVisible();
  await item.getByTestId("item-edit").click();
  const unitPrice = item.getByTestId("edit-unit_price");
  await unitPrice.fill("1234.50");
  await item.getByTestId("item-save").click();
  await expect(item.getByTestId("cell-unit_price")).toContainText("1,234.50");

  await expect(page.getByTestId("approve")).toBeEnabled();
  await page.getByTestId("approve").click();
  await expect(page).toHaveURL(/\/$/);

  await expect.poll(() => sheetRows().filter((r) => r[2] === "of-0003.pdf").length, { timeout: 15_000 }).toBeGreaterThan(0);
  const edited = sheetRows().find((r) => r[2] === "of-0003.pdf" && r[3] === "0")!;
  expect(Number(edited[7])).toBe(1234.5); // unit_price column
  expect(edited[13]).toBe("TRUE"); // reviewer_edited
});

test("approve stays blocked while a high flag is unresolved", async ({ page, request }) => {
  const id = await uploadViaApi(request, "of-0032"); // effective date 06/04/2024 is ambiguous -> blank -> high
  await openForm(page, id);
  await expect(page.getByTestId("approve")).toBeDisabled();
  await expect(page.getByText(/Approve is blocked until 1 high-severity flag/)).toBeVisible();

  const response = await request.post(`/api/forms/${id}/approve`);
  expect(response.status()).toBe(409);

  const header = page.getByTestId("header-card");
  await header.getByTestId("header-edit").click();
  await header.getByTestId("edit-effective_date").fill("06/04/2024");
  await header.getByTestId("header-save").click();
  await expect(header.getByText("Use YYYY-MM-DD")).toBeVisible();
  await expect(page.getByTestId("approve")).toBeDisabled();

  await header.getByTestId("edit-effective_date").fill("2024-06-04");
  await header.getByTestId("header-save").click();
  await expect(page.getByTestId("approve")).toBeEnabled();
});

test("editing quantity recomputes the amount and the line total", async ({ page, request }) => {
  const id = await uploadViaApi(request, "of-0032"); // one item, 1 x $28,669.30 monthly for 12 months
  await openForm(page, id);
  const item = page.getByTestId("item-row").first();
  await item.getByTestId("item-edit").click();
  await item.getByTestId("edit-qty").fill("2");
  await expect(item.getByTestId("amount-preview")).toContainText("688,063.20");
  await item.getByTestId("item-save").click();
  await expect(item.getByTestId("cell-amount")).toContainText("688,063.20");
  await expect(page.getByTestId("line-total")).toContainText("688,063.20");
  await expect(page.getByText(/≠ grand total/)).toBeVisible();
});

test("keyboard: j selects the next flagged row, a accepts it", async ({ page, request }) => {
  const id = await uploadViaApi(request, "of-0041"); // four items with a flagged billing frequency (medium)
  await openForm(page, id);
  const flagged = page.locator("[data-testid=item-row].bg-amber-50");
  await expect(flagged.first()).toBeVisible();
  const before = await flagged.count();
  await page.keyboard.press("j");
  await expect(page.locator("[data-row].outline-indigo-500")).toHaveCount(1);
  await page.keyboard.press("a");
  await expect(flagged).toHaveCount(before - 1);
});

// Clicking a field jumps to its page and marks the quote in the pdf.js text layer.
const HIGHLIGHTS: [string, string, string][] = [
  ["of-0032", "[data-testid=header-contract_signed_date_buying_company]", "07 Jun 2024"],
  ["of-0032", "[data-testid=item-row] >> nth=0 >> [data-testid=cell-amount]", "$344,031.60"],
  ["of-0004", "[data-testid=header-grand_total]", "928,046.55"],
  ["of-0004", "[data-testid=item-row] >> nth=0 >> [data-testid=cell-service_end]", "2024-06-01"],
  ["of-0007", "[data-testid=item-row] >> nth=0 >> [data-testid=cell-amount]", "219,131.88"],
  ["of-0007", "[data-testid=header-contract_signed_date_buying_company]", "27-Jun-2023"],
];

for (const form of [...new Set(HIGHLIGHTS.map(([f]) => f))]) {
  test(`click-to-highlight on ${form}`, async ({ page, request }) => {
    const id = await uploadViaApi(request, form);
    await openForm(page, id);
    for (const [, selector, expected] of HIGHLIGHTS.filter(([f]) => f === form)) {
      await page.locator(selector).click();
      await expect(page.locator("mark.pdf-mark").first()).toBeVisible();
      await expect.poll(async () => (await page.locator("mark.pdf-mark").allTextContents()).join(" ")).toContain(expected);
    }
  });
}
