import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  BadgeCheck,
  CircleAlert,
  ClipboardCheck,
  ShieldCheck,
  ShoppingBag,
  ArrowDownLeft,
  RotateCcw,
} from "lucide-react";
import {
  api,
  type Mandate,
  type Proposal,
  type RecoveryCase,
  type LedgerEntry,
  type LedgerVerify,
  type CreateMandate,
  type Payment,
} from "./api";
import {
  date,
  grantModeLabel,
  money,
  parseMoney,
  parseInteger,
  vaultModeLabel,
  type Action,
  type View,
} from "./domain";
import { PageTitle, Empty } from "./ui";
import { BudgetOverview, SpendingCards } from "./OverviewFunding";
export function Overview({
  grant,
  mandates,
  activeGrants,
  selectGrant,
  proposals,
  payments,
  cases,
  ledger,
  verify,
  setView,
  working,
  action,
  createGrant,
  paypalConfigured,
  vaultAutonomyVerified = false,
}: {
  grant: Mandate | null;
  mandates: Mandate[];
  activeGrants: Mandate[];
  selectGrant: (id: string) => void;
  proposals: Proposal[];
  payments: Payment[];
  cases: RecoveryCase[];
  ledger: LedgerEntry[];
  verify: LedgerVerify | null;
  setView: (view: View) => void;
  working: boolean;
  action: Action;
  createGrant: (body: CreateMandate) => Promise<void>;
  paypalConfigured: boolean;
  vaultAutonomyVerified?: boolean;
}) {
  const [budget, setBudget] = useState("500");
  const [cap, setCap] = useState("400");
  const [constraint, setConstraint] = useState("160");
  const [preferredMode, setPreferredMode] = useState<"buyer" | "vault">("buyer");
  const [creatingGrant, setCreatingGrant] = useState(false);
  const [vaultLink, setVaultLink] = useState<{
    grantId: string;
    approvalUrl: string;
  } | null>(null);
  useEffect(() => {
    if (!creatingGrant) return;
    const input = document.getElementById("grant-budget");
    input?.scrollIntoView({
      block: "center",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
    input?.focus({ preventScroll: true });
  }, [creatingGrant]);
  async function submitGrant(event: React.FormEvent) {
    event.preventDefault();
    await action(async () => {
      await createGrant({
        budget_cents: parseMoney(budget, "Budget", 1),
        per_transaction_cents: parseMoney(cap, "Per-purchase cap", 1),
        allowed_categories: ["furniture", "electronics"],
        allowed_merchants: ["demo-merchant"],
        constraints: {
          width_cm: parseInteger(constraint, "Desk width", 10000),
        },
        instruction: `Office furniture and electronics. Desk width must be ${constraint} cm.`,
        expires_in_minutes: 60,
        velocity_limit: 5,
      });
      setCreatingGrant(false);
    }, preferredMode === "vault" ? "Grant created. Complete the $1.00 PayPal vault authorization below to enable Autonomous (vaulted) mode." : "Spending grant created.");
  }
  return (
    <>
      <PageTitle
        eyebrow="YOUR WORKSPACE"
        title="Spending overview"
        detail="Manage grants, purchases and recovery."
        action={
          <button
            className="button-dark"
            aria-label="New proposal"
            onClick={() => setView("proposals")}
          >
            <ShoppingBag size={16} /> <span>New proposal</span>
          </button>
        }
      />
      <div className="overview-grid">
        <SpendingCards
          grant={grant}
          grants={activeGrants}
          selectGrant={selectGrant}
          newProposal={() => setView("proposals")}
          openPayments={() => setView("payments")}
          newGrant={() => setCreatingGrant(true)}
        />
        <section className="panel transactions-panel">
          <div className="panel-heading">
            <h2>Transactions</h2>
            <button className="text-link" onClick={() => setView("payments")}>
              View all <ArrowUpRight size={14} />
            </button>
          </div>
          {payments.length === 0 ? (
            <Empty
              icon={<ArrowDownLeft />}
              title="Your first purchase starts here"
              copy="Payments will appear here as you check out approved proposals."
              button="Explore proposals"
              onClick={() => setView("proposals")}
            />
          ) : (
            <div className="transaction-list">
              {payments.slice(0, 4).map((payment) => {
                const proposal = proposals.find(
                  (item) => item.id === payment.proposal_id,
                );
                const captured = payment.status === "CAPTURED";
                return (
                  <button
                    className="transaction-row"
                    key={payment.id}
                    onClick={() => setView("payments")}
                  >
                    <span
                      className={`transaction-icon ${captured ? "settled" : ""}`}
                    >
                      <ShoppingBag size={18} aria-hidden="true" />
                    </span>
                    <span className="transaction-main">
                      <strong>
                        {proposal?.items
                          .map((item) => item.name ?? item.product_id)
                          .join(", ") || "Catalog purchase"}
                      </strong>
                      <small>{date(payment.created_at)}</small>
                    </span>
                    <span className="transaction-value">
                      <strong>
                        {captured ? "−" : ""}
                        {money(payment.amount_cents)}
                      </strong>
                      <small>
                        {payment.status.replaceAll("_", " ").toLowerCase()}
                      </small>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
          {payments.some((payment) => payment.refunded_cents > 0) && (
            <button
              className="refund-summary"
              onClick={() => setView("recovery")}
            >
              <RotateCcw size={14} aria-hidden="true" />
              <span>Refunds received</span>
              <strong>
                +
                {money(
                  payments.reduce(
                    (total, payment) => total + payment.refunded_cents,
                    0,
                  ),
                )}
              </strong>
              <ArrowUpRight size={14} aria-hidden="true" />
            </button>
          )}
        </section>
        <BudgetOverview
          grant={grant}
          openCases={cases.filter((item) => item.status === "PROPOSED").length}
        />
        <section className="panel grant-panel">
          <div className="panel-heading">
            <div>
              <h2>
                {creatingGrant
                  ? "Authorize another grant"
                  : grant
                    ? "Office furniture grant"
                    : mandates.length
                      ? "Authorize a spending grant"
                      : "Set your first grant"}
              </h2>
            </div>
            <span
              className={`status-pill ${grant && !creatingGrant ? "active" : "draft"}`}
            >
              <span />
              {creatingGrant ? "Draft" : grant ? grant.status : "Not set"}
            </span>
          </div>
          {grant && !creatingGrant ? (
            <>
              <div className="grant-details">
                <div>
                  <span>Transaction cap</span>
                  <strong>{money(grant.per_transaction_cents)}</strong>
                </div>
                <div>
                  <span>Permitted category</span>
                  <strong>{grant.allowed_categories.join(", ")}</strong>
                </div>
                <div>
                  <span>Desk width</span>
                  <strong>
                    {String(grant.constraints.width_cm ?? "—")} cm
                  </strong>
                </div>
                <div>
                  <span>Expires</span>
                  <strong>{date(grant.expires_at)}</strong>
                </div>
                <div>
                  <span>Payment mode</span>
                  <strong>{grantModeLabel(grant, vaultAutonomyVerified)}</strong>
                </div>
                <div>
                  <span>Vault status</span>
                  <strong>{grant.vault_status}</strong>
                </div>
              </div>
              {grant.vault_status !== "GRANTED" && (
                <div className="vault-controls">
                  {vaultLink?.grantId === grant.id && (
                    <a
                      className="button-outline"
                      href={vaultLink.approvalUrl}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Approve $1.00 PayPal vault setup <ArrowUpRight size={14} />
                    </a>
                  )}
                  <button
                    className="button-outline"
                    disabled={working || !paypalConfigured}
                    title={
                      !paypalConfigured
                        ? "PayPal Sandbox is not configured in this environment."
                        : undefined
                    }
                    onClick={() =>
                      void action(async () => {
                        const res = await api.initVaultGrant(grant.id);
                        setVaultLink({
                          grantId: grant.id,
                          approvalUrl: res.approval_url,
                        });
                      }, "Vault setup order created. Approve in PayPal, then complete the grant.")
                    }
                  >
                    {grant.vault_status === "PENDING"
                      ? "Re-init PayPal vault ($1.00 refundable)"
                      : "Enable Autonomous (vaulted)"}
                  </button>
                  {grant.vault_status === "PENDING" && grant.grant_order_id && (
                    <button
                      className="button-dark"
                      disabled={working || !paypalConfigured}
                      title={
                        !paypalConfigured
                          ? "PayPal Sandbox is not configured in this environment."
                          : undefined
                      }
                      onClick={() =>
                        void action(async () => {
                          await api.completeVaultGrant(grant.id);
                          setVaultLink(null);
                        }, "PayPal vault grant enabled and $1.00 authorization refunded.")
                      }
                    >
                      Complete vault grant
                    </button>
                  )}
                  {!paypalConfigured && (
                    <p className="inline-alert">
                      PayPal Sandbox is not configured in this environment. Vault grant setup requires PayPal Sandbox credentials.
                    </p>
                  )}
                </div>
              )}
              <div className="grant-footer-actions">
                <button
                  className="button-quiet danger"
                  disabled={working}
                  onClick={() =>
                    void action(() => api.revoke(grant.id), "Grant revoked.")
                  }
                >
                  Revoke future spending
                </button>
                <button
                  className="button-quiet"
                  disabled={working}
                  onClick={() => setCreatingGrant(true)}
                >
                  Create another grant
                </button>
              </div>
            </>
          ) : (
            <form className="grant-form" onSubmit={(e) => void submitGrant(e)}>
              <div className="form-row">
                <label>
                  Budget · USD
                  <input
                    id="grant-budget"
                    type="number"
                    min="0.01"
                    step="0.01"
                    required
                    value={budget}
                    onChange={(e) => setBudget(e.target.value)}
                  />
                </label>
                <label>
                  Per-purchase cap
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    required
                    value={cap}
                    onChange={(e) => setCap(e.target.value)}
                  />
                </label>
              </div>
              <label>
                Purchase rules
                <input value="Office furniture & electronics · demo-merchant" readOnly />
              </label>
              <label>
                Payment mode
                <div className="mode-toggle" role="group" aria-label="Payment mode">
                  <button
                    type="button"
                    className={`mode-option ${preferredMode === "buyer" ? "active" : ""}`}
                    onClick={() => setPreferredMode("buyer")}
                  >
                    Buyer approves each purchase
                  </button>
                  <button
                    type="button"
                    className={`mode-option ${preferredMode === "vault" ? "active" : ""}`}
                    onClick={() => setPreferredMode("vault")}
                  >
                    {vaultModeLabel(vaultAutonomyVerified)}
                  </button>
                </div>
              </label>
              <label>
                Desk width · cm
                <input
                  type="number"
                  value={constraint}
                  onChange={(e) => setConstraint(e.target.value)}
                />
              </label>
              <button className="button-dark full" disabled={working}>
                <ShieldCheck size={16} /> Authorize {budget || "0"} USD grant
              </button>
              <small>Includes the demo merchant · expires in 60 minutes</small>
              {grant && (
                <button
                  type="button"
                  className="button-quiet"
                  disabled={working}
                  onClick={() => setCreatingGrant(false)}
                >
                  Cancel new grant
                </button>
              )}
            </form>
          )}
        </section>
        <section className="panel recent-panel">
          <div className="panel-heading">
            <div>
              <h2>Recent proposals</h2>
            </div>
            <button className="text-link" onClick={() => setView("proposals")}>
              All proposals <ArrowUpRight size={14} />
            </button>
          </div>
          {proposals.length === 0 ? (
            <Empty
              icon={<ClipboardCheck />}
              title="No proposals yet"
              copy="Start with a desk from the approved catalog and see the policy engine at work."
              button="Review proposals"
              onClick={() => setView("proposals")}
            />
          ) : (
            <div className="activity-list">
              {proposals.slice(0, 4).map((p) => (
                <div className="activity-row" key={p.id}>
                  <div className={`decision-mark ${p.decision.toLowerCase()}`}>
                    {p.decision === "APPROVE" ? (
                      <BadgeCheck size={16} />
                    ) : (
                      <CircleAlert size={16} />
                    )}
                  </div>
                  <div className="activity-main">
                    <strong>
                      {p.items.map((i) => i.name ?? i.product_id).join(", ")}
                    </strong>
                    <span>
                      {p.decision} · {date(p.created_at)}
                    </span>
                  </div>
                  <b>{money(p.total_cents)}</b>
                </div>
              ))}
            </div>
          )}
        </section>
        <section className="panel ledger-peek">
          <div className="panel-heading">
            <div>
              <h2>Decision ledger</h2>
            </div>
            <button
              className="icon-button"
              aria-label="Open ledger"
              onClick={() => setView("ledger")}
            >
              <ArrowUpRight size={16} />
            </button>
          </div>
          <div className="ledger-state">
            <div className="ledger-check" aria-hidden="true">
              <ShieldCheck size={19} />
            </div>
            <div>
              <strong>
                {proposals.length > 0
                  ? `${proposals.length} recorded ${proposals.length === 1 ? "decision" : "decisions"}`
                  : "Awaiting first decision"}
              </strong>
              <span>
                {verify?.valid
                  ? "Hash chain verified"
                  : verify
                    ? "Hash chain check failed"
                    : "Verification unavailable"}
              </span>
            </div>
          </div>
          {ledger.slice(0, 2).map((row) => (
            <div className="ledger-line" key={row.id}>
              <span>{row.event_type.replaceAll("_", " ")}</span>
              <time>{date(row.created_at)}</time>
            </div>
          ))}
          <button className="text-link" onClick={() => setView("ledger")}>
            View audit history <ArrowUpRight size={14} />
          </button>
        </section>
      </div>
      <div className="overview-appendix">
        {mandates.length > 0 && (
          <section className="panel grant-history">
            <h2>Grant history</h2>
            {mandates.map((item) => (
              <div className="grant-history-row" key={item.id}>
                <div>
                  <strong>{item.instruction}</strong>
                  <small>
                    {item.id.slice(0, 8)} · Expires {date(item.expires_at)}
                  </small>
                </div>
                <span
                  className={`status-pill ${activeGrants.some((active) => active.id === item.id) ? "active" : "draft"}`}
                >
                  {activeGrants.some((active) => active.id === item.id)
                    ? "ACTIVE"
                    : item.status === "ACTIVE"
                      ? "EXPIRED"
                      : item.status}
                </span>
                <b>{money(item.budget_cents)}</b>
                {item.status !== "REVOKED" &&
                  !activeGrants.some((active) => active.id === item.id) && (
                    <button
                      className="button-quiet danger"
                      disabled={working}
                      onClick={() =>
                        void action(() => api.revoke(item.id), "Grant revoked.")
                      }
                    >
                      Revoke expired grant
                    </button>
                  )}
              </div>
            ))}
          </section>
        )}
        <section className="panel rule-card">
          <h2>Authority stays with you.</h2>
          <div className="rule-step">
            <span>01</span>
            <div>
              <b>You define the boundary</b>
              <p>Budget, merchant, category and product constraints.</p>
            </div>
          </div>
          <div className="rule-step">
            <span>02</span>
            <div>
              <b>Mandate checks every cart</b>
              <p>Approve, escalate or deny against the same rules.</p>
            </div>
          </div>
          <div className="rule-step">
            <span>03</span>
            <div>
              <b>You decide what happens next</b>
              <p>Revoke a grant or accept a bounded recovery offer.</p>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}
