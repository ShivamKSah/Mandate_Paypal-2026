import { useMemo } from "react";
import { ArrowUpRight, CircleAlert, WalletCards } from "lucide-react";
import { api, type Mandate, type Payment, type Proposal } from "./api";
import { date, grantModeLabel, money, paymentActions, type Action } from "./domain";
import { PageTitle, Empty } from "./ui";
export function Payments({
  payments,
  proposals,
  mandates,
  now,
  working,
  action,
  configured,
  callbackOrderId,
}: {
  payments: Payment[];
  proposals: Proposal[];
  mandates: Mandate[];
  now: number;
  working: boolean;
  action: Action;
  configured: boolean;
  callbackOrderId: string | null;
}) {
  const byProposal = useMemo(
    () => new Map(proposals.map((p) => [p.id, p])),
    [proposals],
  );
  return (
    <>
      <PageTitle
        eyebrow="FUNDS AND RESERVATIONS"
        title="Payment activity"
        detail="A reservation is not a capture. Provider status is shown exactly as the backend reports it."
      />
      {!configured && (
        <div className="wide-callout">
          <CircleAlert size={18} />
          <div>
            <b>Checkout is unavailable in this environment</b>
            <p>
              PayPal is not configured. There are no simulated captures, refunds
              or approval URLs.
            </p>
          </div>
        </div>
      )}
      <section className="panel payment-panel">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">PAYMENT QUEUE</div>
            <h2>Payments and reservations</h2>
          </div>
          <span className="count-chip">{payments.length} records</span>
        </div>
        {payments.length ? (
          payments.map((pay) => {
            const proposal = byProposal.get(pay.proposal_id);
            const grant = mandates.find(
              (item) => item.id === proposal?.mandate_id,
            );
            const available = paymentActions(pay, proposal, grant, now);
            const returnedOrder = Boolean(
              callbackOrderId && pay.provider_order_id === callbackOrderId,
            );
            return (
              <div
                className={`payment-row ${returnedOrder ? "callback-match" : ""}`}
                key={pay.id}
                id={returnedOrder ? "paypal-return-order" : undefined}
              >
                <div className="payment-symbol">
                  <WalletCards size={19} />
                </div>
                <div className="payment-desc">
                  <strong>
                    {proposal?.items
                      .map((i) => i.name ?? i.product_id)
                      .join(", ") ?? "Proposal payment"}
                  </strong>
                  <span>
                    {pay.status.replaceAll("_", " ")} · {grantModeLabel(grant)} ·{" "}
                    {pay.id.slice(0, 10)} · {date(pay.created_at)}
                  </span>
                  {returnedOrder && (
                    <em className="return-tag">
                      Return URL matches this stored order
                    </em>
                  )}
                </div>
                <div className="payment-amount">
                  <b>{money(pay.amount_cents)}</b>
                  <small>Refunded {money(pay.refunded_cents)}</small>
                  {pay.status === "CAPTURED" && (
                    <small>Net outflow {money(pay.amount_cents - pay.refunded_cents)}</small>
                  )}
                </div>
                {available.unresolved && (
                  <p className="inline-alert">
                    Provider outcome is unresolved. Reservation retained;
                    reconciliation must finish before another payment action.
                  </p>
                )}
                {available.blocked && (
                  <p className="inline-alert">
                    Spending authority is unavailable or has changed. This
                    payment cannot proceed under the current grant.
                  </p>
                )}
                <div className="payment-actions">
                  {pay.can_cancel && (
                    <button
                      className="button-quiet danger"
                      disabled={working}
                      onClick={() =>
                        void action(
                          () => api.cancelPayment(pay.id),
                          "Reservation cancelled and budget released.",
                        )
                      }
                    >
                      Cancel reservation
                    </button>
                  )}
                  {available.approval && configured && pay.approval_url && (
                    <a
                      className="button-outline"
                      href={pay.approval_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Continue with PayPal <ArrowUpRight size={14} />
                    </a>
                  )}
                  {available.vaultCharge && (
                    <button
                      className="button-dark"
                      disabled={working || !configured}
                      title={
                        !configured
                          ? "PayPal Sandbox is not configured in this environment."
                          : undefined
                      }
                      onClick={() =>
                        void action(
                          () => api.vaultCharge(pay.id),
                          "Autonomous vault charge completed.",
                        )
                      }
                    >
                      Charge vaulted PayPal
                    </button>
                  )}
                  {available.checkout && (
                    <button
                      className="button-quiet"
                      disabled={working || !configured}
                      title={
                        !configured
                          ? "PayPal Sandbox is not configured in this environment."
                          : undefined
                      }
                      onClick={() =>
                        void action(
                          () => api.checkout(pay.id),
                          "Checkout request completed.",
                        )
                      }
                    >
                      {available.vaultCharge
                        ? "Fallback: buyer checkout"
                        : "Start checkout"}
                    </button>
                  )}
                  {available.capture && (
                    <button
                      className="button-quiet"
                      disabled={working || !configured}
                      title={
                        !configured
                          ? "PayPal Sandbox is not configured in this environment."
                          : undefined
                      }
                      onClick={() =>
                        void action(
                          () => api.capture(pay.id),
                          "Capture request completed.",
                        )
                      }
                    >
                      Capture order after buyer approval
                    </button>
                  )}
                  {!configured &&
                    (available.vaultCharge ||
                      available.checkout ||
                      available.capture) && (
                      <p className="inline-alert">
                        PayPal Sandbox is not configured in this environment — live payment actions are disabled.
                      </p>
                    )}
                </div>
              </div>
            );
          })
        ) : (
          <Empty
            icon={<WalletCards />}
            title="No payment records"
            copy="An approved proposal will create a reservation here. Capture status only changes after the provider confirms it."
          />
        )}
      </section>
      <section className="panel payment-note">
        <div className="eyebrow">STATUS GUIDE</div>
        <div className="status-guide">
          <span>
            <i className="dot reserved" />
            Reserved
          </span>
          <p>Budget is held for an approved cart; money has not moved.</p>
        </div>
        <div className="status-guide">
          <span>
            <i className="dot captured" />
            Captured
          </span>
          <p>Provider confirmed a capture. Only then can recovery be opened.</p>
        </div>
      </section>
    </>
  );
}
