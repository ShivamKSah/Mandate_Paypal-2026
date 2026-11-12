import type { Mandate, Payment, Proposal, RecoveryCase } from "./api.ts";
export type View =
  | "overview"
  | "proposals"
  | "challenge"
  | "payments"
  | "recovery"
  | "ledger";
export type Action = (
  run: () => Promise<unknown>,
  success: string,
) => Promise<void>;
export const money = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    cents / 100,
  );
export const date = (value: string) =>
  new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
    timeZoneName: "short",
  });
export function message(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Try again.";
}
export function parseMoney(value: string, label: string, minimum = 0): number {
  if (!/^\d+(?:\.\d{1,2})?$/.test(value))
    throw new Error(
      `${label} must be a dollar amount with at most two decimal places.`,
    );
  const [dollars, fraction = ""] = value.split(".");
  const cents = Number(dollars) * 100 + Number(fraction.padEnd(2, "0"));
  if (!Number.isSafeInteger(cents) || cents < minimum || cents > 100_000_000)
    throw new Error(
      `${label} must be between ${money(minimum)} and $1,000,000.00.`,
    );
  return cents;
}
export function parseInteger(
  value: string,
  label: string,
  maximum: number,
): number {
  const number = Number(value);
  if (
    !/^\d+$/.test(value) ||
    !Number.isSafeInteger(number) ||
    number < 1 ||
    number > maximum
  )
    throw new Error(`${label} must be a whole number from 1 to ${maximum}.`);
  return number;
}
export function activeGrants(mandates: Mandate[], now = Date.now()): Mandate[] {
  return mandates.filter(
    (grant) => grant.status === "ACTIVE" && Date.parse(grant.expires_at) > now,
  );
}
function currentAuthority(
  proposal: Proposal,
  grant: Mandate | undefined,
  now: number,
) {
  return Boolean(
    grant &&
      grant.id === proposal.mandate_id &&
      grant.status === "ACTIVE" &&
      Date.parse(grant.expires_at) > now &&
      grant.version === proposal.grant_version,
  );
}
export function canApproveProposal(
  proposal: Proposal,
  grant: Mandate | undefined,
  now = Date.now(),
) {
  return (
    proposal.decision === "ESCALATE" &&
    proposal.status === "ESCALATED" &&
    Date.parse(proposal.expires_at) > now &&
    Date.parse(proposal.quote_expires_at) > now &&
    currentAuthority(proposal, grant, now)
  );
}
export function grantModeLabel(grant: Mandate | undefined | null): string {
  return grant?.vault_status === "GRANTED"
    ? "Autonomous (vaulted)"
    : "Buyer approves each purchase";
}

export function paymentActions(
  payment: Payment,
  proposal: Proposal | undefined,
  grant: Mandate | undefined,
  now = Date.now(),
) {
  const authorized = Boolean(
    proposal &&
      proposal.id === payment.proposal_id &&
      proposal.decision === "APPROVE" &&
      proposal.status === "APPROVED" &&
      currentAuthority(proposal, grant, now),
  );
  return {
    checkout: authorized && payment.status === "RESERVED",
    vaultCharge:
      authorized &&
      payment.status === "RESERVED" &&
      grant?.vault_status === "GRANTED",
    approval:
      authorized &&
      payment.status === "ORDER_CREATED" &&
      Boolean(payment.approval_url),
    capture:
      authorized &&
      payment.status === "ORDER_CREATED" &&
      Boolean(payment.provider_order_id),
    blocked:
      !authorized && ["RESERVED", "ORDER_CREATED"].includes(payment.status),
    unresolved:
      payment.status === "UNKNOWN" || payment.status === "CAPTURE_PENDING",
  };
}
export function recoverablePayments(payments: Payment[], cases: RecoveryCase[]) {
  const activeCases = new Set(
    cases
      .filter((item) =>
        !["REJECTED", "REFUNDED", "REFUND_FAILED"].includes(item.status),
      )
      .map((item) => item.payment_id),
  );
  return payments.filter(
    (payment) =>
      payment.status === "CAPTURED" &&
      payment.provider_capture_id &&
      payment.refunded_cents < payment.amount_cents &&
      !activeCases.has(payment.id),
  );
}
