import assert from "node:assert/strict";
import { test } from "node:test";
import {
  activeGrants,
  canApproveProposal,
  grantModeLabel,
  parseInteger,
  parseMoney,
  paymentActions,
  recoverablePayments,
} from "../src/domain.ts";
import {
  api,
  ApiError,
  MandateSchema,
  PaymentSchema,
  setCsrf,
} from "../src/api.ts";

const grant = {
  id: "grant",
  status: "ACTIVE",
  budget_cents: 50000,
  per_transaction_cents: 50000,
  allowed_categories: ["furniture"],
  allowed_merchants: ["demo-merchant"],
  constraints: { width_cm: 160 },
  instruction: "A 160 cm desk",
  expires_at: "2026-10-30T12:00:00Z",
  spent_cents: 0,
  reserved_cents: 0,
  available_cents: 50000,
  version: 1,
  vault_status: "NONE",
};
const payment = {
  id: "payment",
  proposal_id: "proposal",
  status: "ORDER_CREATED",
  amount_cents: 34900,
  refunded_cents: 0,
  can_cancel: false,
  provider_order_id: "ORDER123",
  provider_capture_id: null,
  approval_url: "https://www.sandbox.paypal.com/checkoutnow?token=ORDER123",
  created_at: "2026-10-30T11:00:00Z",
};
const proposal = {
  id: "proposal", mandate_id: grant.id, decision: "APPROVE", status: "APPROVED",
  total_cents: 34900, currency: "USD", cart_hash: "a".repeat(64), rules: [], items: [],
  created_at: "2026-10-30T11:00:00Z", expires_at: "2026-10-30T11:05:00Z",
  quote_expires_at: "2026-10-30T11:01:00Z", grant_version: 1,
};
const now = Date.parse("2026-10-30T11:00:00Z");
const session = {
  id: "public-id",
  csrf_token: "csrf-test-token",
  mode: "unconfigured",
  paypal_configured: false,
  authenticated: true,
  access_required: true,
};

test("money is parsed exactly and never silently rounds invalid precision", () => {
  assert.equal(parseMoney("87.25", "Amount"), 8725);
  assert.equal(parseMoney("0.29", "Amount"), 29);
  assert.equal(parseMoney("1000000.00", "Amount"), 100000000);
  for (const input of [
    "",
    " ",
    "1.005",
    "1e2",
    "-1",
    "+2",
    "Infinity",
    "1,000",
    "1000000.01",
  ])
    assert.throws(() => parseMoney(input, "Amount"), undefined, input);
  assert.throws(() => parseMoney("0", "Budget", 1));
  for (const input of ["", "0", "1.5", "1e1", "101"])
    assert.throws(() => parseInteger(input, "Quantity", 100));
});

test("expired and revoked grants cannot be selected for spending", () => {
  const now = Date.parse("2026-10-30T11:00:00Z");
  const expired = {
    ...grant,
    id: "expired",
    expires_at: new Date(now).toISOString(),
  };
  const revoked = { ...grant, id: "revoked", status: "REVOKED" };
  assert.deepEqual(
    activeGrants([expired, revoked, grant], now).map((value) => value.id),
    ["grant"],
  );
  assert.deepEqual(activeGrants([expired, revoked], now), []);
});

test("only an order-created payment permits capture, including after a forged return URL", () => {
  for (const status of [
    "UNKNOWN",
    "CAPTURE_PENDING",
    "CAPTURED",
    "FAILED",
    "RELEASED",
    "RESERVED",
  ]) {
    const actions = paymentActions(PaymentSchema.parse({ ...payment, status }), proposal, grant, now);
    assert.equal(actions.capture, false, status);
    assert.equal(actions.approval, false, status);
    assert.equal(actions.checkout, status === "RESERVED", status);
  }
  assert.equal(paymentActions(PaymentSchema.parse(payment), proposal, grant, now).capture, true);
  assert.equal(
    paymentActions(PaymentSchema.parse({ ...payment, provider_order_id: null }), proposal, grant, now)
      .capture,
    false,
  );
});

test("payment controls require current authority while identical approved carts can be revalidated after quote expiry", () => {
  const afterQuoteExpiry = now + 10 * 60_000;
  assert.equal(paymentActions(payment, proposal, grant, afterQuoteExpiry).capture, true);
  for (const authority of [undefined, { ...grant, status: "REVOKED" }, { ...grant, version: 2 }, { ...grant, expires_at: proposal.created_at }]) {
    const actions = paymentActions(payment, proposal, authority, now);
    assert.equal(actions.capture, false);
    assert.equal(actions.approval, false);
    assert.equal(actions.blocked, true);
    assert.equal(paymentActions({ ...payment, status: "RESERVED" }, proposal, authority, now).checkout, false);
  }
  assert.equal(paymentActions(payment, undefined, grant, now).capture, false);
  assert.equal(paymentActions(payment, { ...proposal, status: "CANCELLED" }, grant, now).capture, false);
});

test("escalations need both approval windows and the current grant version", () => {
  const escalation = { ...proposal, decision: "ESCALATE", status: "ESCALATED" };
  assert.equal(canApproveProposal(escalation, grant, now), true);
  assert.equal(canApproveProposal(escalation, grant, Date.parse(escalation.quote_expires_at)), false);
  assert.equal(canApproveProposal({ ...escalation, expires_at: proposal.created_at }, grant, now), false);
  assert.equal(canApproveProposal(escalation, { ...grant, version: 2 }, now), false);
  assert.equal(canApproveProposal(escalation, { ...grant, status: "REVOKED" }, now), false);
  assert.equal(canApproveProposal(proposal, grant, now), false);
});

test("recovery excludes fully refunded captures and payments with active cases", () => {
  const captured = { ...payment, status: "CAPTURED", provider_capture_id: "CAPTURE123" };
  assert.deepEqual(recoverablePayments([captured], []), [captured]);
  assert.deepEqual(recoverablePayments([payment, { ...captured, refunded_cents: captured.amount_cents }], []), []);
  for (const status of ["OPEN", "PROPOSED", "ACCEPTED", "REFUND_PENDING", "UNKNOWN"])
    assert.deepEqual(recoverablePayments([captured], [{ payment_id: payment.id, status }]), [], status);
  for (const status of ["REJECTED", "REFUNDED", "REFUND_FAILED"])
    assert.deepEqual(recoverablePayments([captured], [{ payment_id: payment.id, status }]), [captured], status);
});

test("financial responses reject fractional cents, malformed times, unknown states and unsafe redirect URLs", () => {
  for (const invalid of [
    { amount_cents: 1.5 },
    { amount_cents: -1 },
    { amount_cents: Number.MAX_SAFE_INTEGER + 1 },
    { status: "APPROVED_BY_QUERY" },
    { created_at: "yesterday" },
    { approval_url: "javascript:alert(1)" },
    { approval_url: "https://sandbox.paypal.com.evil.example/" },
    { approval_url: "https://user:secret@sandbox.paypal.com/" },
    { approval_url: "https://sandbox.paypal.com:8443/" },
    { approval_url: "https://www.paypal.com/checkoutnow" },
  ])
    assert.equal(
      PaymentSchema.safeParse({ ...payment, ...invalid }).success,
      false,
    );
  assert.equal(
    MandateSchema.safeParse({ ...grant, available_cents: 0.5 }).success,
    false,
  );
});

test("session initialization shares one in-flight request before the browser cookie arrives", async (t) => {
  let calls = 0;
  let finish;
  t.mock.method(globalThis, "fetch", () => {
    calls += 1;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  const first = api.session();
  const second = api.session();
  assert.equal(calls, 1);
  finish(Response.json(session));
  assert.deepEqual(await first, await second);
});

test("logout includes the current CSRF token and accepts an empty 204 response", async (t) => {
  setCsrf("csrf-test-token");
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/logout");
    assert.equal(options.credentials, "include");
    assert.equal(options.headers["X-CSRF-Token"], "csrf-test-token");
    return new Response(null, { status: 204 });
  });
  assert.equal(await api.logout(), undefined);
});

test("reservation cancellation posts the CSRF token and reads the released payment capability", async (t) => {
  setCsrf("csrf-test-token");
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/payments/payment/cancel");
    assert.equal(options.method, "POST");
    assert.equal(options.headers["X-CSRF-Token"], "csrf-test-token");
    assert.deepEqual(JSON.parse(options.body), {});
    return Response.json({ ...payment, status: "RELEASED", can_cancel: false });
  });
  const released = await api.cancelPayment(payment.id);
  assert.equal(released.status, "RELEASED");
  assert.equal(released.can_cancel, false);
});

test("the login gate receives a typed unauthorized response", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json({ detail: "Access required" }, { status: 401 }),
  );
  await assert.rejects(
    api.session(),
    (error) => error instanceof ApiError && error.status === 401,
  );
});

test("invalid agent results fail at the response boundary", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json({ summary: "Done", proposal: { decision: "APPROVE" } }),
  );
  await assert.rejects(
    api.agentRun("grant", "Find a desk"),
    /Unexpected response/,
  );
});

test("vault charge capability requires granted vault status and current authority", () => {
  const reserved = PaymentSchema.parse({
    ...payment,
    status: "RESERVED",
    provider_order_id: null,
    approval_url: null,
  });
  assert.equal(grantModeLabel(grant), "Buyer approves each purchase");
  assert.equal(paymentActions(reserved, proposal, grant, now).vaultCharge, false);
  const vaulted = MandateSchema.parse({ ...grant, vault_status: "GRANTED" });
  assert.equal(grantModeLabel(vaulted), "Autonomous (vaulted)");
  assert.equal(paymentActions(reserved, proposal, vaulted, now).vaultCharge, true);
  assert.equal(
    paymentActions(reserved, proposal, { ...vaulted, status: "REVOKED" }, now)
      .vaultCharge,
    false,
  );
});
