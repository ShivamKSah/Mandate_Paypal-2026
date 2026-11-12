import type { AttackResult, Mandate, Payment, Proposal, RecoveryCase } from "./api.ts";
import { recoverablePayments } from "./domain.ts";

export interface GuidedStepStatus {
  grantCreated: boolean;
  mouseProposed: boolean;
  attacksBlocked: boolean;
  ambiguityApproved: boolean;
  refundAccepted: boolean;
}

export const GUIDED_ATTACK_IDS = [
  "over_budget",
  "lookalike_merchant",
  "currency_swap",
] as const;

export function deriveGuidedStepStatus({
  grant,
  proposals,
  cases,
  attackResults,
}: {
  grant: Mandate | null;
  proposals: Proposal[];
  cases: RecoveryCase[];
  attackResults: AttackResult[];
}): GuidedStepStatus {
  const grantCreated = Boolean(grant);
  const mouseProposed = proposals.some((p) =>
    p.items.some((item) => item.product_id === "mouse-ergonomic"),
  );
  const attacksBlocked =
    GUIDED_ATTACK_IDS.every((id) =>
      attackResults.some((res) => res.attack_id === id && !res.breached),
    );
  const ambiguityApproved = proposals.some(
    (p) =>
      p.decision === "ESCALATE" &&
      p.status === "APPROVED" &&
      p.items.some((item) => item.product_id === "desk-unknown"),
  );
  const refundAccepted = cases.some((c) => c.status === "REFUNDED");

  return {
    grantCreated,
    mouseProposed,
    attacksBlocked,
    ambiguityApproved,
    refundAccepted,
  };
}

export function canRunGuidedRecovery(
  paypalConfigured: boolean,
  payments: Payment[],
  cases: RecoveryCase[],
): { allowed: boolean; targetPayment: Payment | null; reason: string | null } {
  if (!paypalConfigured) {
    return {
      allowed: false,
      targetPayment: null,
      reason:
        "PayPal Sandbox is not configured in this environment. Steps 1–4 still work offline without PayPal.",
    };
  }
  const recoverable = recoverablePayments(payments, cases);
  if (!recoverable.length) {
    return {
      allowed: false,
      targetPayment: null,
      reason:
        "Requires a confirmed PayPal CAPTURED payment first (charge via Payments tab after approving an order).",
    };
  }
  return { allowed: true, targetPayment: recoverable[0], reason: null };
}
