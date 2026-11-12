import { useState } from "react";
import { ClipboardCheck, LockKeyhole, RotateCcw } from "lucide-react";
import { api, CauseSchema, type Payment, type RecoveryCase } from "./api";
import {
  date,
  money,
  parseMoney,
  recoverablePayments,
  type Action,
} from "./domain";
import { PageTitle, Empty } from "./ui";
export function Recovery({
  cases,
  payments,
  configured,
  working,
  action,
}: {
  cases: RecoveryCase[];
  payments: Payment[];
  configured: boolean;
  working: boolean;
  action: Action;
}) {
  const captured = recoverablePayments(payments, cases);
  const [paymentId, setPaymentId] = useState("");
  const [cause, setCause] = useState("seller_error");
  const [evidence, setEvidence] = useState("");
  const [freight, setFreight] = useState("60");
  const [resale, setResale] = useState("87.25");
  async function open(event: React.FormEvent) {
    event.preventDefault();
    await action(
      () =>
        api.createCase({
          payment_id: paymentId,
          cause: CauseSchema.parse(cause),
          evidence,
          avoided_freight_cents: parseMoney(freight, "Avoided freight"),
          resale_loss_cents: parseMoney(resale, "Resale loss"),
        }),
      "Recovery case prepared. Review the proposed offer below.",
    );
  }
  return (
    <>
      <PageTitle
        eyebrow="HUMAN-BOUNDED RECOVERY"
        title="Resolve a purchase issue"
        detail="A refund is proposed from evidence and economics. Nothing is sent to PayPal until you accept."
      />
      {captured.length === 0 && (
        <div className="wide-callout muted">
          <LockKeyhole size={18} />
          <div>
            <b>No payment is available for a new recovery case</b>
            <p>
              Recovery requires a confirmed capture with a refundable balance
              and no active case. Review existing offers below.
            </p>
          </div>
        </div>
      )}
      <div className="split-panels recovery-grid">
        <form className="panel form-panel" onSubmit={(e) => void open(e)}>
          <div className="eyebrow">NEW RECOVERY CASE</div>
          <h2>Report what happened</h2>
          <label>
            Captured payment
            <select
              required
              disabled={!captured.length}
              value={
                captured.some((payment) => payment.id === paymentId)
                  ? paymentId
                  : ""
              }
              onChange={(e) => setPaymentId(e.target.value)}
            >
              <option value="">Choose a captured payment…</option>
              {captured.map((p) => (
                <option key={p.id} value={p.id}>
                  {money(p.amount_cents)} · {p.id.slice(0, 10)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Cause
            <select value={cause} onChange={(e) => setCause(e.target.value)}>
              <option value="seller_error">Seller error</option>
              <option value="ambiguous_listing">Ambiguous listing</option>
              <option value="agent_error">Agent error</option>
              <option value="vague_instruction">Vague instruction</option>
            </select>
          </label>
          <label>
            Evidence
            <textarea
              required
              rows={4}
              maxLength={8000}
              placeholder="Describe the issue and the evidence you reviewed…"
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
            />
          </label>
          <div className="form-row">
            <label>
              Avoided freight · USD
              <input
                type="number"
                min="0"
                step="0.01"
                value={freight}
                onChange={(e) => setFreight(e.target.value)}
              />
            </label>
            <label>
              Expected resale loss · USD
              <input
                type="number"
                min="0"
                step="0.01"
                value={resale}
                onChange={(e) => setResale(e.target.value)}
              />
            </label>
          </div>
          <small className="policy-note">
            Economic inputs and refund bands are demo business policy, not
            consumer entitlement or PayPal policy.
          </small>
          <button
            className="button-dark"
            disabled={
              working ||
              !captured.some((payment) => payment.id === paymentId) ||
              !evidence.trim()
            }
          >
            <ClipboardCheck size={16} /> Calculate bounded offer
          </button>
        </form>
        <section className="panel results-panel">
          <div className="eyebrow">CASES NEEDING YOUR REVIEW</div>
          <h2>Recovery offers</h2>
          {cases.length === 0 ? (
            <Empty
              icon={<RotateCcw />}
              title="No recovery cases"
              copy="Once a real capture exists, describe what happened and inspect the proposed amount."
            />
          ) : (
            cases.map((c) => {
              const proposed = c.status === "PROPOSED";
              return (
                <article className="case-card" key={c.id}>
                  <div className="case-head">
                    <span
                      className={`status-pill ${proposed ? "draft" : "active"}`}
                    >
                      {c.status}
                    </span>
                    <time>{date(c.created_at)}</time>
                  </div>
                  <h3>{c.cause.replaceAll("_", " ")}</h3>
                  <p>{c.explanation}</p>
                  <blockquote>{c.evidence}</blockquote>
                  <div className="offer-line">
                    <span>Proposed refund</span>
                    <strong>{money(c.offer_cents)}</strong>
                  </div>
                  {proposed && (
                    <div className="case-buttons">
                      <button
                        className="button-dark"
                        disabled={working || (c.offer_cents > 0 && !configured)}
                        title={
                          c.offer_cents > 0 && !configured
                            ? "PayPal is not configured"
                            : undefined
                        }
                        onClick={() =>
                          void action(
                            () => api.acceptCase(c),
                            "Offer acceptance recorded. Review the provider status below.",
                          )
                        }
                      >
                        Accept offer
                      </button>
                      <button
                        className="button-quiet danger"
                        disabled={working}
                        onClick={() =>
                          void action(
                            () => api.rejectCase(c.id),
                            "Offer rejected.",
                          )
                        }
                      >
                        Reject
                      </button>
                    </div>
                  )}
                  {proposed && c.offer_cents > 0 && !configured && (
                    <p className="inline-alert">
                      PayPal must be configured before this refund can be
                      accepted.
                    </p>
                  )}
                </article>
              );
            })
          )}
        </section>
      </div>
    </>
  );
}
