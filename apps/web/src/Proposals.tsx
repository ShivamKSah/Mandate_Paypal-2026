import { useState } from "react";
import { z } from "zod";
import {
  ArrowUpRight,
  BadgeCheck,
  Boxes,
  CircleAlert,
  ShieldCheck,
  ShoppingBag,
} from "lucide-react";
import {
  api,
  type Mandate,
  type Product,
  type Proposal,
  type CreateProposal,
} from "./api";
import {
  canApproveProposal,
  date,
  money,
  parseMoney,
  parseInteger,
  type Action,
  type View,
} from "./domain";
import { PageTitle, Empty } from "./ui";
const PendingIntentSchema = z.object({
  payload: z.string(),
  id: z.string().regex(/^dashboard-[a-f0-9-]{36}$/),
});

export function Proposals({
  grant,
  mandates,
  now,
  setView,
  products,
  proposals,
  working,
  action,
}: {
  grant: Mandate | null;
  mandates: Mandate[];
  now: number;
  setView: (view: View) => void;
  products: Product[];
  proposals: Proposal[];
  working: boolean;
  action: Action;
}) {
  const [selected, setSelected] = useState("desk-160");
  const [quantity, setQuantity] = useState("1");
  const [customTotal, setCustomTotal] = useState("");
  const [agentInstruction, setAgentInstruction] = useState(
    "Find a desk that meets my approved width requirement.",
  );
  const latest = proposals.find(
    (proposal) => proposal.mandate_id === grant?.id,
  );
  const product = products.find((p) => p.id === selected);
  const scenarios = [
    {
      id: "desk-160",
      title: "Within grant",
      subtitle: "160 cm desk · expected approval",
      product: "desk-160",
      total: "",
    },
    {
      id: "desk-unknown",
      title: "Missing specification",
      subtitle: "Width absent · ambiguity check",
      product: "desk-unknown",
      total: "",
    },
    {
      id: "gift-card",
      title: "Untrusted merchant",
      subtitle: "Gift card · merchant boundary",
      product: "gift-card",
      total: "",
    },
    {
      id: "subscription",
      title: "Recurring purchase",
      subtitle: "Subscription · frequency rule",
      product: "subscription",
      total: "",
    },
    {
      id: "overclaim",
      title: "Inflated total",
      subtitle: "Claimed total exceeds catalog",
      product: "desk-160",
      total: "49900",
    },
  ];
  async function propose(productId = selected, claim = customTotal, units = quantity) {
    if (!grant) return;
    await action(async () => {
      const body = {
        mandate_id: grant.id,
        items: [
          {
            product_id: productId,
            quantity: parseInteger(units, "Quantity", 100),
          },
        ],
        currency: "USD",
      } satisfies Omit<CreateProposal, "purchase_intent_id">;
      const claimedTotal = claim
        ? { claimed_total_cents: parseMoney(claim, "Claimed total") }
        : {};
      const payload = JSON.stringify({ ...body, ...claimedTotal });
      const storageKey = `mandate.pending-proposal.${grant.id}`;
      let stored: unknown;
      try {
        stored = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
      } catch {
        stored = null;
      }
      const prior = PendingIntentSchema.safeParse(stored);
      const pending =
        prior.success && prior.data.payload === payload
          ? prior.data
          : { payload, id: `dashboard-${crypto.randomUUID()}` };
      sessionStorage.setItem(storageKey, JSON.stringify(pending));
      await api.propose({
        ...body,
        ...claimedTotal,
        purchase_intent_id: pending.id,
      });
      sessionStorage.removeItem(storageKey);
    }, "Proposal evaluated by the policy engine.");
  }
  return (
    <>
      <PageTitle
        eyebrow="CONTROL THE CART"
        title="Proposal desk"
        detail="Every scenario goes through the live policy endpoint. Nothing bypasses the rules."
      />
      {grant && (
        <p className="selected-grant-note">
          Using grant {grant.id.slice(0, 8)} · {money(grant.available_cents)}{" "}
          available
        </p>
      )}
      <div className="scenario-grid">
        {scenarios.map((s, i) => (
          <button
            className="scenario-card"
            key={s.id}
            disabled={working || !grant}
            onClick={() =>
              void propose(
                s.product,
                s.total ? String(Number(s.total) / 100) : "",
                "1",
              )
            }
          >
            <span className="scenario-number">0{i + 1}</span>
            <span className="scenario-arrow">
              <ArrowUpRight size={15} />
            </span>
            <strong>{s.title}</strong>
            <small>{s.subtitle}</small>
          </button>
        ))}
      </div>
      <div className="split-panels">
        <section className="panel form-panel">
          <div className="eyebrow">CUSTOM PROPOSAL</div>
          <h2>Build a cart</h2>
          {!grant && (
            <div className="inline-alert">
              <p>Create a spending grant before submitting a proposal.</p>
              <button
                className="button-quiet"
                onClick={() => setView("overview")}
              >
                Create a spending grant
              </button>
            </div>
          )}
          <label>
            Catalog item
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              {products.map((p) => (
                <option value={p.id} key={p.id}>
                  {p.name} · {money(p.unit_price_cents)} · {p.merchant_id}
                </option>
              ))}
            </select>
          </label>
          <div className="form-row">
            <label>
              Quantity
              <input
                type="number"
                min="1"
                max="100"
                step="1"
                required
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </label>
            <label>
              Claimed total · optional
              <input
                type="number"
                min="0"
                step="0.01"
                placeholder={
                  product
                    ? money(product.unit_price_cents * Number(quantity))
                    : "—"
                }
                value={customTotal}
                onChange={(e) => setCustomTotal(e.target.value)}
              />
            </label>
          </div>
          {product && (
            <div className="product-note">
              <Boxes size={17} />
              <div>
                <b>{product.name}</b>
                <span>
                  {product.description} · {product.category} ·{" "}
                  {product.merchant_id}
                </span>
              </div>
            </div>
          )}
          <button
            className="button-dark"
            disabled={working || !grant || !product}
            onClick={() => void propose()}
          >
            <ShieldCheck size={16} /> Evaluate proposal
          </button>
          <div className="agent-run">
            <div className="eyebrow">OPTIONAL MODEL RUN</div>
            <label>
              Shopping instruction
              <textarea
                rows={2}
                maxLength={4000}
                value={agentInstruction}
                onChange={(e) => setAgentInstruction(e.target.value)}
              />
            </label>
            <button
              className="button-quiet"
              disabled={working || !grant || !agentInstruction.trim()}
              onClick={() =>
                grant &&
                void action(
                  () => api.agentRun(grant.id, agentInstruction),
                  "Agent run completed.",
                )
              }
            >
              Run shopping agent <ArrowUpRight size={14} />
            </button>
            <small>
              Requires a configured model key. If unavailable, the API explains
              why.
            </small>
          </div>
        </section>
        <section className="panel results-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">POLICY OUTCOME</div>
              <h2>
                {latest
                  ? decisionLabel(latest.decision)
                  : "Awaiting a proposal"}
              </h2>
            </div>
            {latest && (
              <span className={`decision-tag ${latest.decision.toLowerCase()}`}>
                {latest.decision}
              </span>
            )}
          </div>
          {latest ? (
            <>
              <div className="result-total">
                <span>Canonical cart total</span>
                <strong>{money(latest.total_cents)}</strong>
              </div>
              <div className="rule-list">
                {latest.rules.map((rule) => (
                  <div className="rule-result" key={rule.id}>
                    <span className={`rule-icon ${rule.status.toLowerCase()}`}>
                      {rule.status === "PASS" ? (
                        <BadgeCheck size={15} />
                      ) : (
                        <CircleAlert size={15} />
                      )}
                    </span>
                    <div>
                      <b>{rule.name}</b>
                      <p>{rule.message}</p>
                    </div>
                    <em>{rule.status}</em>
                  </div>
                ))}
              </div>
              <small className="hash-line">
                Cart binding · {latest.cart_hash.slice(0, 20)}…
              </small>
              {canApproveProposal(latest, grant ?? undefined, now) && (
                <button
                  className="button-dark approve-escalation"
                  disabled={working}
                  onClick={() =>
                    void action(
                      () => api.approve(latest),
                      "Escalation approved against the stored cart hash.",
                    )
                  }
                >
                  Approve this proposal
                </button>
              )}
              {latest.status === "ESCALATED" &&
                !canApproveProposal(latest, grant ?? undefined, now) && (
                  <p className="inline-alert">
                    This approval window or grant is no longer valid. Submit a
                    fresh proposal.
                  </p>
                )}
            </>
          ) : (
            <Empty
              icon={<ShieldCheck />}
              title="Policy results appear here"
              copy="Choose a preset to exercise the same checks used for real proposals."
            />
          )}
        </section>
      </div>
      <section className="panel history-panel">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">SESSION HISTORY</div>
            <h2>
              All proposals <small>{proposals.length}</small>
            </h2>
          </div>
        </div>
        {proposals.length ? (
          proposals.map((p) => (
            <div className="history-row" key={p.id}>
              <span className={`decision-tag ${p.decision.toLowerCase()}`}>
                {p.decision}
              </span>
              <strong>
                {p.items.map((i) => i.name ?? i.product_id).join(", ")}
              </strong>
              <span>{p.id.slice(0, 9)}</span>
              <b>{money(p.total_cents)}</b>
              <div className="history-review">
                <time>{date(p.created_at)}</time>
                {canApproveProposal(
                  p,
                  mandates.find((item) => item.id === p.mandate_id),
                  now,
                ) && (
                  <button
                    className="text-link"
                    disabled={working}
                    onClick={() =>
                      void action(
                        () => api.approve(p),
                        "Escalation approved against the stored cart hash.",
                      )
                    }
                  >
                    Approve proposal
                  </button>
                )}
              </div>
            </div>
          ))
        ) : (
          <Empty
            icon={<ShoppingBag />}
            title="Nothing submitted"
            copy="Your proposals will appear here after policy evaluation."
          />
        )}
      </section>
    </>
  );
}
function decisionLabel(decision: Proposal["decision"]): string {
  switch (decision) {
    case "APPROVE":
      return "Within the boundary";
    case "ESCALATE":
      return "Needs your approval";
    case "DENY":
      return "Blocked by policy";
    default: {
      const exhaustive: never = decision;
      return exhaustive;
    }
  }
}
