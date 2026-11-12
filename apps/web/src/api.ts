import { z } from "zod";
const CentsSchema = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const TimestampSchema = z.iso.datetime({ offset: true });
const HashSchema = z.string().regex(/^[a-f0-9]{64}$/);
export const CauseSchema = z.enum([
  "seller_error",
  "ambiguous_listing",
  "agent_error",
  "vague_instruction",
]);
const ApprovalUrlSchema = z.url().refine((value) => {
  const url = new URL(value);
  return (
    url.protocol === "https:" &&
    ["www.sandbox.paypal.com", "sandbox.paypal.com"].includes(url.hostname) &&
    !url.username &&
    !url.password &&
    (!url.port || url.port === "443")
  );
}, "Expected a PayPal sandbox approval URL");
export const SessionSchema = z.object({
  id: z.string(),
  csrf_token: z.string(),
  mode: z.enum(["sandbox", "unconfigured"]),
  paypal_configured: z.boolean(),
  authenticated: z.boolean(),
  access_required: z.boolean(),
  public_demo: z.boolean().default(false),
});
export const ProductSchema = z.object({
  id: z.string(),
  name: z.string(),
  merchant_id: z.string(),
  category: z.string(),
  unit_price_cents: CentsSchema,
  currency: z.string(),
  attributes: z.record(z.string(), z.unknown()),
  recurring: z.boolean(),
  description: z.string(),
});
export const MandateSchema = z.object({
  id: z.string(),
  status: z.enum(["ACTIVE", "EXPIRED", "REVOKED"]),
  budget_cents: CentsSchema,
  per_transaction_cents: CentsSchema,
  allowed_categories: z.array(z.string()),
  allowed_merchants: z.array(z.string()),
  constraints: z.record(z.string(), z.unknown()),
  instruction: z.string(),
  expires_at: TimestampSchema,
  spent_cents: CentsSchema,
  reserved_cents: CentsSchema,
  available_cents: CentsSchema,
  version: z.number().int().positive(),
  vault_status: z
    .enum(["NONE", "PENDING", "GRANTED", "FAILED", "REVOKED"])
    .default("NONE"),
  grant_order_id: z.string().nullable().optional(),
});
const GrantInitSchema = z.object({
  mandate: MandateSchema,
  order_id: z.string(),
  approval_url: ApprovalUrlSchema,
});
const GrantCompleteSchema = z.object({
  mandate: MandateSchema,
  vault_status: z.string(),
  masked_vault_id: z.string().optional(),
  refund_status: z.string(),
});
const RuleSchema = z.object({
  id: z.string(),
  name: z.string(),
  status: z.enum(["PASS", "DENY", "ESCALATE", "NOT_RUN"]),
  message: z.string(),
});
export const ProposalSchema = z.object({
  id: z.string(),
  mandate_id: z.string(),
  decision: z.enum(["APPROVE", "ESCALATE", "DENY"]),
  status: z.enum([
    "RECEIVED",
    "APPROVED",
    "ESCALATED",
    "DENIED",
    "EXPIRED",
    "CANCELLED",
  ]),
  total_cents: CentsSchema,
  currency: z.string(),
  cart_hash: HashSchema,
  rules: z.array(RuleSchema),
  items: z.array(
    z
      .object({
        product_id: z.string(),
        name: z.string().optional(),
        quantity: z.number().int().positive(),
        unit_price_cents: CentsSchema.optional(),
      })
      .passthrough(),
  ),
  created_at: TimestampSchema,
  expires_at: TimestampSchema,
  quote_expires_at: TimestampSchema,
  grant_version: z.number().int().positive(),
  payment_id: z.string().nullable().optional(),
});
export const PaymentSchema = z.object({
  id: z.string(),
  proposal_id: z.string(),
  status: z.enum([
    "RESERVED",
    "ORDER_CREATED",
    "CAPTURE_PENDING",
    "CAPTURED",
    "UNKNOWN",
    "FAILED",
    "RELEASED",
  ]),
  amount_cents: CentsSchema,
  refunded_cents: CentsSchema,
  can_cancel: z.boolean(),
  provider_order_id: z.string().nullable().optional(),
  provider_capture_id: z.string().nullable().optional(),
  approval_url: ApprovalUrlSchema.nullable().optional(),
  created_at: TimestampSchema,
});
export const CaseSchema = z.object({
  id: z.string(),
  payment_id: z.string(),
  status: z.enum([
    "OPEN",
    "PROPOSED",
    "ACCEPTED",
    "REJECTED",
    "REFUND_PENDING",
    "REFUNDED",
    "REFUND_FAILED",
    "UNKNOWN",
  ]),
  cause: CauseSchema,
  evidence: z.string(),
  offer_cents: CentsSchema,
  offer_hash: HashSchema,
  explanation: z.string(),
  created_at: TimestampSchema,
});
const LedgerSchema = z.object({
  id: z.string(),
  event_type: z.string(),
  entity_id: z.string(),
  details: z.record(z.string(), z.unknown()),
  created_at: TimestampSchema,
  prev_hash: z.string(),
  row_hash: HashSchema,
});
const VerifySchema = z.object({
  valid: z.boolean(),
  event_count: z.number().int().nonnegative(),
  checkpoint: z.string().nullable().optional(),
});
export const AttackItemSchema = z.object({
  id: z.string(),
  expected_rule: z.string(),
  title: z.string(),
  description: z.string(),
});
export const AttackResultSchema = z.object({
  id: z.string(),
  attack_id: z.string(),
  title: z.string(),
  description: z.string(),
  verdict: z.string(),
  expected_rule: z.string(),
  actual_rule: z.string(),
  triggered_rules: z.array(z.string()),
  breached: z.boolean(),
  rules: z.array(RuleSchema),
});
export const RunAllAttacksSchema = z.object({
  attempts: z.number().int().nonnegative(),
  breaches: z.number().int().nonnegative(),
  blocked: z.number().int().nonnegative(),
  results: z.array(AttackResultSchema),
});
export const ChallengeStatsSchema = z.object({
  attempts: z.number().int().nonnegative(),
  breaches: z.number().int().nonnegative(),
  per_rule_counts: z.record(z.string(), z.number().int().nonnegative()),
});
export const EvalResultsSchema = z.object({
  label: z.string(),
  benchmark_date: z.string(),
  attack_kinds: z.array(z.string()).default([]),
  attack_coverage: z.string().optional(),
  sample_size: z.object({
    total_evaluations: z.number().int(),
    attack_scenarios: z.number().int(),
    legitimate_purchases: z.number().int(),
  }),
  summary: z.object({
    attacks_blocked: z.string(),
    false_positives: z.string(),
    escalate_on_legitimate: z.string(),
  }),
  metrics: z.object({
    block_rate_pct: z.number(),
    block_rate_95ci: z.tuple([z.number(), z.number()]),
    false_positive_rate_pct: z.number(),
    false_positive_rate_95ci: z.tuple([z.number(), z.number()]),
    escalate_on_legitimate_pct: z.number(),
    escalate_on_legitimate_95ci: z.tuple([z.number(), z.number()]),
    attacks_blocked_count: z.number().int(),
    attacks_breached_count: z.number().int(),
    approved_legitimate_count: z.number().int(),
    escalated_legitimate_count: z.number().int(),
    false_positive_count: z.number().int(),
  }),
  escalated_legitimate_scenarios: z.array(
    z.object({
      scenario: z.string(),
      product_id: z.string(),
      reasons: z.array(z.string()),
    }),
  ),
  latency_ms: z.object({
    p50: z.number(),
    p95: z.number(),
    mean: z.number(),
  }),
});
const ErrorSchema = z.object({
  detail: z.union([z.string(), z.array(z.object({ msg: z.string() }))]),
});
const CreateMandateSchema = z.object({
  budget_cents: CentsSchema.positive().max(100_000_000),
  per_transaction_cents: CentsSchema.positive().max(100_000_000),
  allowed_categories: z.array(z.string()).min(1),
  allowed_merchants: z.array(z.string()).min(1),
  constraints: z.record(
    z.string(),
    z.union([z.string(), z.number().int(), z.boolean()]),
  ),
  instruction: z.string().min(1).max(4000),
  expires_in_minutes: z.number().int().min(1).max(1440),
  velocity_limit: z.number().int().min(1).max(100),
});
const CreateProposalSchema = z.object({
  mandate_id: z.string(),
  purchase_intent_id: z.string().min(1).max(120),
  items: z
    .array(
      z.object({
        product_id: z.string(),
        quantity: z.number().int().min(1).max(100),
      }),
    )
    .min(1),
  currency: z.literal("USD"),
  claimed_total_cents: CentsSchema.max(100_000_000).optional(),
});
const CreateCaseSchema = z.object({
  payment_id: z.string(),
  cause: CauseSchema,
  evidence: z.string().trim().min(1).max(8000),
  avoided_freight_cents: CentsSchema.max(100_000_000),
  resale_loss_cents: CentsSchema.max(100_000_000),
});
export type CreateMandate = z.infer<typeof CreateMandateSchema>;
export type CreateProposal = z.infer<typeof CreateProposalSchema>;
export type CreateCase = z.infer<typeof CreateCaseSchema>;
export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}
export type Session = z.infer<typeof SessionSchema>;
export type Product = z.infer<typeof ProductSchema>;
export type Mandate = z.infer<typeof MandateSchema>;
export type Proposal = z.infer<typeof ProposalSchema>;
export type Payment = z.infer<typeof PaymentSchema>;
export type RecoveryCase = z.infer<typeof CaseSchema>;
export type LedgerEntry = z.infer<typeof LedgerSchema>;
export type LedgerVerify = z.infer<typeof VerifySchema>;
export type AttackItem = z.infer<typeof AttackItemSchema>;
export type AttackResult = z.infer<typeof AttackResultSchema>;
export type ChallengeStats = z.infer<typeof ChallengeStatsSchema>;
export type EvalResults = z.infer<typeof EvalResultsSchema>;
export type AgentRunResponse = {
  summary: string;
  llm_fallback: boolean;
  planner_label?: string;
  proposal: Proposal;
};
let csrfToken = "";
export function setCsrf(token: string): void {
  csrfToken = token;
}
async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.method && options.method !== "GET"
        ? { "X-CSRF-Token": csrfToken }
        : {}),
      ...options.headers,
    },
  });
  const body: unknown =
    response.status === 204
      ? undefined
      : await response.json().catch(() => null);
  if (!response.ok) {
    const parsedError = ErrorSchema.safeParse(body);
    const detail = parsedError.success
      ? parsedError.data.detail
      : `Request failed (${response.status})`;
    throw new ApiError(
      typeof detail === "string"
        ? detail
        : detail.map((issue) => issue.msg).join("; "),
      response.status,
    );
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) throw new Error(`Unexpected response from ${path}`);
  return parsed.data;
}
const list = <T>(schema: z.ZodType<T>) => z.array(schema);
const post = (body: unknown): RequestInit => ({
  method: "POST",
  body: JSON.stringify(body),
});
let sessionRequest: Promise<Session> | null = null;
function session(): Promise<Session> {
  // StrictMode can run mount effects twice before the first session cookie arrives.
  sessionRequest ??= request("/session", SessionSchema).finally(() => {
    sessionRequest = null;
  });
  return sessionRequest;
}
export const api = {
  session,
  login: (access_key: string) =>
    request("/login", SessionSchema, post({ access_key })),
  logout: () => request("/logout", z.undefined(), post({})),
  resetSession: () => request("/session/reset", SessionSchema, post({})),
  catalog: () => request("/catalog", list(ProductSchema)),
  mandates: () => request("/mandates", list(MandateSchema)),
  createMandate: (body: CreateMandate) =>
    request("/mandates", MandateSchema, post(CreateMandateSchema.parse(body))),
  revoke: (id: string) =>
    request(`/mandates/${id}/revoke`, MandateSchema, post({})),
  initVaultGrant: (id: string) =>
    request(`/mandates/${id}/grant/init`, GrantInitSchema, post({})),
  completeVaultGrant: (id: string, order_id?: string) =>
    request(
      `/mandates/${id}/grant/complete`,
      GrantCompleteSchema,
      post(order_id ? { order_id } : {}),
    ),
  proposals: () => request("/proposals", list(ProposalSchema)),
  propose: (body: CreateProposal) =>
    request(
      "/proposals",
      ProposalSchema,
      post(CreateProposalSchema.parse(body)),
    ),
  approve: (p: Proposal) =>
    request(
      `/proposals/${p.id}/approve`,
      ProposalSchema,
      post({ cart_hash: p.cart_hash }),
    ),
  payments: () => request("/payments", list(PaymentSchema)),
  checkout: (id: string) =>
    request(`/payments/${id}/checkout`, PaymentSchema, post({})),
  vaultCharge: (id: string) =>
    request(`/payments/${id}/vault-charge`, PaymentSchema, post({})),
  cancelPayment: (id: string) =>
    request(`/payments/${id}/cancel`, PaymentSchema, post({})),
  capture: (id: string) =>
    request(`/payments/${id}/capture`, PaymentSchema, post({})),
  cases: () => request("/cases", list(CaseSchema)),
  createCase: (body: CreateCase) =>
    request("/cases", CaseSchema, post(CreateCaseSchema.parse(body))),
  acceptCase: (c: RecoveryCase) =>
    request(
      `/cases/${c.id}/accept`,
      CaseSchema,
      post({ offer_hash: c.offer_hash }),
    ),
  rejectCase: (id: string) =>
    request(`/cases/${id}/reject`, CaseSchema, post({})),
  suggestCause: (payment_id: string, evidence: string) =>
    request(
      "/cases/suggest-cause",
      z.object({
        suggested_cause: CauseSchema,
        explanation: z.string(),
        policy_band_pct: z.tuple([z.number().int(), z.number().int()]),
        llm_fallback: z.boolean(),
      }),
      post({ payment_id, evidence }),
    ),
  ledger: () =>
    request("/ledger", list(LedgerSchema)).then((entries) => entries.reverse()),
  verifyLedger: () => request("/ledger/verify", VerifySchema),
  attacks: () => request("/attacks", list(AttackItemSchema)),
  runAttack: (attack_id: string) =>
    request("/attacks/run", AttackResultSchema, post({ attack_id })),
  runAllAttacks: () =>
    request("/attacks/run-all", RunAllAttacksSchema, post({})),
  challengeStats: () => request("/challenge/stats", ChallengeStatsSchema),
  evals: () => request("/evals", EvalResultsSchema),
  agentRun: (mandate_id: string, instruction: string, allow_fallback = false) =>
    request(
      "/agent-runs",
      z.object({
        summary: z.string(),
        llm_fallback: z.boolean().default(false),
        planner_label: z.string().optional(),
        proposal: ProposalSchema,
      }),
      post({
        mandate_id,
        instruction: z.string().trim().min(1).max(4000).parse(instruction),
        allow_fallback,
      }),
    ),
};
