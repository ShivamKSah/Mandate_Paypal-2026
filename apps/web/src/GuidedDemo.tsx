import { useState } from "react";
import { BadgeCheck, CircleAlert, Play } from "lucide-react";
import {
  api,
  type AgentRunResponse,
  type AttackResult,
  type CreateMandate,
  type Mandate,
  type Payment,
  type Proposal,
  type RecoveryCase,
} from "./api";
import type { Action, View } from "./domain";
import { PageTitle } from "./ui";
import {
  canRunGuidedRecovery,
  deriveGuidedStepStatus,
  GUIDED_ATTACK_IDS,
} from "./guidedDemoLogic";

export function GuidedDemo({
  grant,
  proposals,
  payments,
  cases,
  paypalConfigured,
  working,
  action,
  createGrant,
  onAgentResult,
  setView,
}: {
  grant: Mandate | null;
  proposals: Proposal[];
  payments: Payment[];
  cases: RecoveryCase[];
  paypalConfigured: boolean;
  working: boolean;
  action: Action;
  createGrant: (body: CreateMandate) => Promise<void>;
  onAgentResult?: (res: AgentRunResponse) => void;
  setView: (view: View) => void;
}) {
  const [attackResults, setAttackResults] = useState<AttackResult[]>([]);
  const status = deriveGuidedStepStatus({
    grant,
    proposals,
    cases,
    attackResults,
  });
  const recoveryCheck = canRunGuidedRecovery(paypalConfigured, payments, cases);

  const completedCount = [
    status.grantCreated,
    status.mouseProposed,
    status.attacksBlocked,
    status.ambiguityApproved,
    status.refundAccepted,
  ].filter(Boolean).length;

  return (
    <>
      <PageTitle
        eyebrow="INTERACTIVE WALKTHROUGH"
        title="Guided demo"
        detail="Step through grant creation, AI shopping, adversarial blocks, escalation, and bounded recovery."
      />
      <section className="panel guided-demo-panel" aria-labelledby="guided-demo-title">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">5-STEP WALKTHROUGH</div>
          <h2 id="guided-demo-title">Guided demo</h2>
        </div>
        <span className="count-chip">{completedCount} / 5 completed</span>
      </div>

      <ol className="guided-list">
        <li className={`guided-step ${status.grantCreated ? "done" : ""}`}>
          <div className="guided-step-info">
            <span className="guided-check" aria-hidden="true">
              {status.grantCreated ? <BadgeCheck size={16} /> : "1"}
            </span>
            <div>
              <strong>Create the demo grant</strong>
              <small>
                $500.00 budget, $400.00 cap, demo-merchant, furniture &amp; electronics · No PayPal login
              </small>
            </div>
          </div>
          <button
            type="button"
            className="button-outline"
            disabled={working || status.grantCreated}
            onClick={() =>
              void action(
                () =>
                  createGrant({
                    budget_cents: 50000,
                    per_transaction_cents: 40000,
                    allowed_categories: ["furniture", "electronics"],
                    allowed_merchants: ["demo-merchant"],
                    constraints: { width_cm: 160 },
                    instruction:
                      "Office furniture and electronics. Desk width must be 160 cm.",
                    expires_in_minutes: 60,
                    velocity_limit: 5,
                  }),
                "Demo spending grant created.",
              )
            }
          >
            <Play size={14} /> {status.grantCreated ? "Grant active" : "Create demo grant"}
          </button>
        </li>

        <li className={`guided-step ${status.mouseProposed ? "done" : ""}`}>
          <div className="guided-step-info">
            <span className="guided-check" aria-hidden="true">
              {status.mouseProposed ? <BadgeCheck size={16} /> : "2"}
            </span>
            <div>
              <strong>Run the agent on &ldquo;buy an ergonomic vertical mouse&rdquo;</strong>
              <small>
                Uses Groq or labeled deterministic rules fallback (`llm_fallback=true`) · No PayPal login
              </small>
            </div>
          </div>
          <button
            type="button"
            className="button-outline"
            disabled={working || !grant}
            onClick={() =>
              grant &&
              void action(async () => {
                const res = await api.agentRun(
                  grant.id,
                  "buy an ergonomic vertical mouse",
                  true,
                );
                onAgentResult?.(res);
                return res;
              }, "Agent submitted ergonomic vertical mouse proposal.")
            }
          >
            <Play size={14} /> Run agent
          </button>
        </li>

        <li className={`guided-step ${status.attacksBlocked ? "done" : ""}`}>
          <div className="guided-step-info">
            <span className="guided-check" aria-hidden="true">
              {status.attacksBlocked ? <BadgeCheck size={16} /> : "3"}
            </span>
            <div>
              <strong>Run three chosen attacks &amp; inspect blocked rules</strong>
              <small>
                over_budget, lookalike_merchant, currency_swap · Zero PayPal calls
              </small>
              {attackResults.length > 0 && (
                <div className="guided-attack-tags">
                  {attackResults.map((res) => (
                    <span
                      key={res.attack_id}
                      className={`attack-outcome ${res.breached ? "bad" : "ok"}`}
                    >
                      {res.attack_id}: {res.breached ? "BREACH" : `Blocked by ${res.actual_rule}`}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
          <button
            type="button"
            className="button-outline"
            disabled={working}
            onClick={() =>
              void action(async () => {
                const results: AttackResult[] = [];
                for (const id of GUIDED_ATTACK_IDS) {
                  results.push(await api.runAttack(id));
                }
                setAttackResults(results);
                return results;
              }, "Three adversarial carts blocked by policy.")
            }
          >
            <Play size={14} /> Run 3 attacks
          </button>
        </li>

        <li className={`guided-step ${status.ambiguityApproved ? "done" : ""}`}>
          <div className="guided-step-info">
            <span className="guided-check" aria-hidden="true">
              {status.ambiguityApproved ? <BadgeCheck size={16} /> : "4"}
            </span>
            <div>
              <strong>Run the ambiguity-gate scenario and approve it</strong>
              <small>
                Submits unlisted-width desk (`P09` ESCALATE), then approves against `cart_hash` · No PayPal login
              </small>
            </div>
          </div>
          <button
            type="button"
            className="button-outline"
            disabled={working || !grant}
            onClick={() =>
              grant &&
              void action(async () => {
                const escalated = await api.propose({
                  mandate_id: grant.id,
                  purchase_intent_id: `guided-ambig-${crypto.randomUUID()}`,
                  items: [{ product_id: "desk-unknown", quantity: 1 }],
                  currency: "USD",
                });
                return api.approve(escalated);
              }, "Ambiguity-gate proposal escalated by P09 and approved.")
            }
          >
            <Play size={14} /> Run &amp; approve ambiguity
          </button>
        </li>

        <li className={`guided-step ${status.refundAccepted ? "done" : ""}`}>
          <div className="guided-step-info">
            <span className="guided-check" aria-hidden="true">
              {status.refundAccepted ? <BadgeCheck size={16} /> : "5"}
            </span>
            <div>
              <strong>
                Open a recovery case and accept a bounded partial refund{" "}
                <span className="status-pill draft">Needs PayPal Sandbox</span>
              </strong>
              <small>
                Executes a real PayPal partial refund against a confirmed CAPTURED payment
              </small>
              {!recoveryCheck.allowed && !status.refundAccepted && recoveryCheck.reason && (
                <p className="inline-alert guided-alert">
                  <CircleAlert size={14} aria-hidden="true" /> {recoveryCheck.reason}{" "}
                  {paypalConfigured && (
                    <button
                      type="button"
                      className="text-link"
                      onClick={() => setView("payments")}
                    >
                      Go to Payments
                    </button>
                  )}
                </p>
              )}
            </div>
          </div>
          <button
            type="button"
            className="button-dark"
            disabled={working || !recoveryCheck.allowed || status.refundAccepted}
            title={!paypalConfigured ? "PayPal is not configured" : undefined}
            onClick={() =>
              recoveryCheck.targetPayment &&
              void action(async () => {
                const created = await api.createCase({
                  payment_id: recoveryCheck.targetPayment!.id,
                  cause: "seller_error",
                  evidence: "Guided demo: wrong item specification delivered",
                  avoided_freight_cents: 5000,
                  resale_loss_cents: 5000,
                });
                return api.acceptCase(created);
              }, "Recovery case opened and bounded partial refund accepted.")
            }
          >
            <Play size={14} />{" "}
            {status.refundAccepted ? "Refunded" : "Open case & refund"}
          </button>
        </li>
      </ol>
    </section>
    </>
  );
}
