import {
  ArrowDownLeft,
  ArrowUpRight,
  Plus,
  ShieldCheck,
  WalletCards,
} from "lucide-react";
import type { Mandate } from "./api";
import { money } from "./domain";

export function BudgetOverview({
  grant,
  openCases,
}: {
  grant: Mandate | null;
  openCases: number;
}) {
  const amounts = [
    {
      key: "available",
      label: "Available",
      cents: grant?.available_cents ?? 0,
    },
    { key: "reserved", label: "Reserved", cents: grant?.reserved_cents ?? 0 },
    { key: "spent", label: "Spent", cents: grant?.spent_cents ?? 0 },
  ];

  return (
    <section className="panel budget-overview" aria-labelledby="budget-title">
      <div className="panel-heading">
        <h2 id="budget-title">Budget overview</h2>
        <span className="count-chip">USD</span>
      </div>
      <div className="grant-total">
        <span>Total authorized</span>
        <strong>{grant ? money(grant.budget_cents) : "—"}</strong>
      </div>
      <div className="budget-allocation">
        <div className="budget-scale" aria-hidden="true">
          <span>Budget allocation</span>
          <span>{grant ? money(grant.budget_cents) : "—"}</span>
        </div>
        <div className="budget-track" aria-hidden="true">
          {grant &&
            amounts.map(({ key, cents }) => (
              <span
                className={`budget-${key}`}
                style={{ flexGrow: cents }}
                key={key}
              />
            ))}
        </div>
        <dl className="budget-breakdown">
          {amounts.map(({ key, label, cents }) => (
            <div key={key}>
              <dt>
                <span className={`budget-${key}`} aria-hidden="true" />
                {label}
              </dt>
              <dd>{grant ? money(cents) : "—"}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="budget-caption">
        <span>Reserved funds are held for approved proposals.</span>
        <span>
          {openCases} open {openCases === 1 ? "case" : "cases"}
        </span>
      </div>
    </section>
  );
}

export function SpendingCards({
  grant,
  grants,
  selectGrant,
  newProposal,
  openPayments,
  newGrant,
}: {
  grant: Mandate | null;
  grants: Mandate[];
  selectGrant: (id: string) => void;
  newProposal: () => void;
  openPayments: () => void;
  newGrant: () => void;
}) {
  const previews = grants
    .filter((item) => item.id !== grant?.id)
    .slice(0, 2)
    .reverse();

  return (
    <section
      className="panel spending-cards"
      aria-labelledby="spending-cards-title"
    >
      <div className="panel-heading">
        <h2 id="spending-cards-title">Your wallet</h2>
        {grants.length > 1 ? (
          <label className="grant-selector wallet-selector">
            <span className="sr-only">Active spending grant</span>
            <select
              value={grant?.id ?? ""}
              onChange={(event) => selectGrant(event.target.value)}
            >
              {grants.map((item) => (
                <option key={item.id} value={item.id}>
                  Grant · {item.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="count-chip">{grants.length} active</span>
        )}
      </div>
      <div className="grant-stack">
        {previews.length === 0 && (
          <div className="grant-card-backing" aria-hidden="true" />
        )}
        {previews.map((item) => (
          <div className="grant-card-peek" aria-hidden="true" key={item.id}>
            <span>Grant {item.id.slice(0, 8)}</span>
            <b>{money(item.available_cents)}</b>
          </div>
        ))}
        <div
          key={grant?.id ?? "empty"}
          className={`grant-card-face${grant ? "" : " grant-card-empty"}`}
        >
          <div className="grant-card-top">
            <span>
              <ShieldCheck size={15} aria-hidden="true" /> Mandate grant
            </span>
            <span className="card-wordmark">m.</span>
          </div>
          <span className="wallet-currency">
            USD <span>·</span> Spending authority
          </span>
          <div className="grant-card-amount">
            <span>
              {grant ? "Available to spend" : "Start with a spending grant"}
            </span>
            <strong>
              {grant ? money(grant.available_cents) : "No active grant"}
            </strong>
          </div>
          <div className="grant-card-bottom">
            <span>
              {grant
                ? `Grant · ${grant.id.slice(0, 8)}`
                : "Your budget. Your boundaries."}
            </span>
            <ShieldCheck size={16} aria-hidden="true" />
          </div>
        </div>
      </div>
      <div className="wallet-actions" aria-label="Wallet actions">
        <button onClick={newProposal}>
          <ArrowUpRight size={19} aria-hidden="true" />
          <span>New proposal</span>
        </button>
        <button onClick={openPayments}>
          <ArrowDownLeft size={19} aria-hidden="true" />
          <span>Payments</span>
        </button>
        <button onClick={newGrant}>
          <Plus size={19} aria-hidden="true" />
          <span>New grant</span>
        </button>
      </div>
      <p className="wallet-note">
        <WalletCards size={13} aria-hidden="true" /> A spending limit, not a
        stored bank balance.
      </p>
    </section>
  );
}
