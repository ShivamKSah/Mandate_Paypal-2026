// Run with playwright-cli run-code. These are explicit API fixtures, not provider evidence.
async (page) => {
  let authenticated = false;
  let initialSessionRequests = 0;
  let proposalExists = false;
  const purchaseIntents = [];
  const session = { id: "public-review-session", csrf_token: "review-csrf", mode: "sandbox", paypal_configured: true, authenticated: true, access_required: true };
  const now = new Date().toISOString();
  const grant = { id: "active-grant", status: "ACTIVE", budget_cents: 50000, per_transaction_cents: 50000, allowed_categories: ["furniture"], allowed_merchants: ["demo-merchant"], constraints: { width_cm: 160 }, instruction: "A 160 cm desk", expires_at: new Date(Date.now() + 3600000).toISOString(), spent_cents: 0, reserved_cents: 34900, available_cents: 15100, version: 1 };
  const payment = { id: "unknown-payment", proposal_id: "proposal", status: "UNKNOWN", amount_cents: 34900, refunded_cents: 0, can_cancel: false, provider_order_id: "ORDER123", provider_capture_id: null, approval_url: "https://www.sandbox.paypal.com/checkoutnow?token=ORDER123", created_at: now };
  const product = { id: "desk-160", name: "160 cm desk", merchant_id: "demo-merchant", category: "furniture", unit_price_cents: 34900, currency: "USD", attributes: { width_cm: 160 }, recurring: false, description: "Review fixture desk" };
  const proposal = { id: "proposal", mandate_id: grant.id, decision: "DENY", status: "DENIED", total_cents: 34900, currency: "USD", cart_hash: "a".repeat(64), rules: [{ id: "P02", name: "Budget", status: "DENY", message: "Insufficient available budget" }], items: [{ product_id: product.id, name: product.name, quantity: 1, unit_price_cents: product.unit_price_cents }], created_at: now, expires_at: new Date(Date.now() + 300000).toISOString(), quote_expires_at: new Date(Date.now() + 60000).toISOString(), grant_version: 1, payment_id: null };
  await page.route("**/api/**", async route => {
    const name = new URL(route.request().url()).pathname.slice(5);
    if (name === "login") {
      if (route.request().postDataJSON().access_key !== "review-example-key") return route.fulfill({ status: 401, json: { detail: "Invalid access key" } });
      authenticated = true;
      return route.fulfill({ json: session });
    }
    if (name === "logout") {
      if (route.request().headers()["x-csrf-token"] !== "review-csrf") throw new Error("Logout omitted CSRF");
      authenticated = false;
      return route.fulfill({ status: 204 });
    }
    if (name === "session") {
      if (!authenticated) initialSessionRequests += 1;
      return route.fulfill(authenticated ? { json: session } : { status: 401, json: { detail: "Access required" } });
    }
    if (name === "proposals" && route.request().method() === "POST") {
      proposalExists = true;
      purchaseIntents.push(route.request().postDataJSON().purchase_intent_id);
      if (purchaseIntents.length === 1) return route.abort("failed");
      return route.fulfill({ json: proposal });
    }
    const resources = {
      catalog: [product], mandates: [grant, { ...grant, id: "expired-grant", expires_at: now }, { ...grant, id: "revoked-grant", status: "REVOKED" }],
      proposals: proposalExists ? [proposal] : [], payments: [payment], cases: [], ledger: [], "ledger/verify": { valid: true, event_count: 0, checkpoint: null },
    };
    if (!(name in resources)) throw new Error(`Unexpected fixture request ${name}`);
    return route.fulfill({ json: resources[name] });
  });
  await page.goto("http://127.0.0.1:5173/?checkout=approved&token=ORDER123");
  await page.getByRole("heading", { name: "Open your workspace" }).waitFor();
  if (initialSessionRequests !== 1) throw new Error(`StrictMode issued ${initialSessionRequests} initial session requests`);
  await page.getByLabel("Access key").fill("wrong-example-key");
  await page.getByRole("button", { name: "Open workspace" }).click();
  await page.getByRole("alert").filter({ hasText: "Invalid access key" }).waitFor();
  await page.getByLabel("Access key").fill("review-example-key");
  await page.getByRole("button", { name: "Open workspace" }).click();
  await page.getByRole("heading", { name: "Payment activity" }).waitFor();
  await page.getByText("Provider outcome is unresolved.", { exact: false }).waitFor();
  if (await page.getByRole("button", { name: /Capture|Start checkout/ }).count()) throw new Error("UNKNOWN payment exposed an executable payment action");
  if (await page.getByRole("link", { name: /Continue with PayPal/ }).count()) throw new Error("UNKNOWN payment exposed its stale approval link");
  await page.getByText("This URL does not confirm approval or capture.", { exact: false }).waitFor();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await page.getByRole("heading", { name: "Office furniture grant" }).waitFor();
  await page.getByText("EXPIRED", { exact: true }).waitFor();
  await page.getByText("REVOKED", { exact: true }).waitFor();
  if (!(await page.locator(".grant-total").innerText()).includes("151.00")) throw new Error("Active grant was not selected");
  await page.setViewportSize({ width: 390, height: 844 });
  if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error("Overview overflows on mobile");
  await page.screenshot({ path: "tests/fixtures-mobile-review.png", fullPage: true });
  await page.getByRole("button", { name: "Proposals", exact: true }).click();
  await page.getByRole("button", { name: "Evaluate proposal", exact: true }).click();
  await page.getByRole("alert").waitFor();
  await page.getByRole("heading", { name: "Blocked by policy" }).waitFor();
  await page.reload();
  await page.getByRole("button", { name: "Proposals", exact: true }).click();
  await page.getByRole("button", { name: "Evaluate proposal", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "Proposal evaluated" }).waitFor();
  if (purchaseIntents.length !== 2 || purchaseIntents[0] !== purchaseIntents[1]) throw new Error("A lost proposal response plus reload changed the purchase intent identity");
  if (await page.evaluate(() => sessionStorage.getItem("mandate.pending-proposal.active-grant")) !== null) throw new Error("A confirmed proposal retained its pending identity");
  await page.getByLabel("Claimed total", { exact: false }).fill("1.005");
  await page.getByRole("button", { name: "Evaluate proposal", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "at most two decimal places" }).waitFor();
  if (purchaseIntents.length !== 2) throw new Error("Invalid money reached the API");
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  await page.getByRole("heading", { name: "Open your workspace" }).waitFor();
  if (await page.getByRole("button", { name: "Revoke future spending" }).count()) throw new Error("Logout retained private dashboard data");
  return "Browser fixtures passed: single session, invalid/valid login, honest callback, UNKNOWN lifecycle controls, grant history, 390px layout, stable proposal retry after reload, strict money, CSRF logout.";
}
