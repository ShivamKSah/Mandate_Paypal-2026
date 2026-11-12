import { useMemo, useState } from "react";
import {
  BadgeCheck,
  CircleAlert,
  FileClock,
  ShieldCheck,
  X,
} from "lucide-react";
import { type LedgerEntry, type LedgerVerify, type Proposal } from "./api";
import { date } from "./domain";
import { Empty, PageTitle } from "./ui";

export function Ledger({
  entries,
  verify,
  proposals = [],
}: {
  entries: LedgerEntry[];
  verify: LedgerVerify | null;
  proposals?: Proposal[];
}) {
  const [selectedId, setSelectedId] = useState<string | null>(
    entries[0]?.id ?? null,
  );
  const selected = useMemo(
    () => entries.find((e) => e.id === selectedId) ?? entries[0] ?? null,
    [entries, selectedId],
  );
  const byProposalId = useMemo(
    () => new Map(proposals.map((p) => [p.id, p])),
    [proposals],
  );
  const byPaymentId = useMemo(
    () =>
      new Map(
        proposals
          .filter((p) => p.payment_id)
          .map((p) => [p.payment_id as string, p]),
      ),
    [proposals],
  );

  const selectedRules = useMemo(() => {
    if (!selected) return null;
    const rawRules = selected.details?.rules;
    if (Array.isArray(rawRules)) {
      return rawRules as Proposal["rules"];
    }
    const directProposal = byProposalId.get(selected.entity_id);
    if (directProposal) return directProposal.rules;
    const detailProposalId =
      typeof selected.details?.proposal_id === "string"
        ? selected.details.proposal_id
        : null;
    if (detailProposalId && byProposalId.has(detailProposalId)) {
      return byProposalId.get(detailProposalId)!.rules;
    }
    const paymentProposal = byPaymentId.get(selected.entity_id);
    if (paymentProposal) return paymentProposal.rules;
    return null;
  }, [selected, byProposalId, byPaymentId]);

  return (
    <>
      <PageTitle
        eyebrow="AUDIT TRAIL"
        title="Decision ledger"
        detail="Append-only SHA-256 hash-chained events. Select any row to inspect payload details and P01–P11 policy checks."
        action={
          verify && (
            <span
              className={`verification ${verify.valid ? "verified" : "invalid"}`}
            >
              {verify.valid ? (
                <ShieldCheck size={16} aria-hidden="true" />
              ) : (
                <CircleAlert size={16} aria-hidden="true" />
              )}
              {verify.valid ? "Chain verified" : "Chain check failed"}
            </span>
          )
        }
      />
      <div className="ledger-summary">
        <div>
          <span>Events recorded</span>
          <strong>{verify?.event_count ?? entries.length}</strong>
        </div>
        <div>
          <span>Integrity check</span>
          <strong>
            {verify ? (verify.valid ? "Valid" : "Invalid") : "Unavailable"}
          </strong>
        </div>
        <div>
          <span>Latest event</span>
          <strong>
            {entries[0] ? date(entries[0].created_at) : "No events yet"}
          </strong>
        </div>
      </div>

      <div className={`ledger-layout ${selected ? "with-drawer" : ""}`}>
        <section className="panel ledger-table">
          <div className="ledger-table-head">
            <span>EVENT</span>
            <span>ENTITY</span>
            <span>RECORDED</span>
            <span>CHAIN HASH</span>
          </div>
          {entries.length ? (
            entries.map((row) => (
              <button
                type="button"
                className={`ledger-row-btn ${selected?.id === row.id ? "selected" : ""}`}
                key={row.id}
                onClick={() => setSelectedId(row.id)}
              >
                <span className="event-title">
                  <i className="ledger-dot" aria-hidden="true" />
                  {row.event_type.replaceAll("_", " ")}
                </span>
                <code>{row.entity_id}</code>
                <time>{date(row.created_at)}</time>
                <code>{row.row_hash.slice(0, 16)}…</code>
              </button>
            ))
          ) : (
            <Empty
              icon={<FileClock />}
              title="Ledger is empty"
              copy="The first grant or policy decision will establish a verifiable event history."
            />
          )}
        </section>

        {selected && (
          <aside className="panel ledger-drawer" aria-label="Event drawer">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">EVENT DRAWER</div>
                <h2>{selected.event_type.replaceAll("_", " ")}</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="Close drawer"
                onClick={() => setSelectedId(null)}
              >
                <X size={16} />
              </button>
            </div>
            <div className="drawer-meta">
              <div>
                <span>Entity</span>
                <code>{selected.entity_id}</code>
              </div>
              <div>
                <span>Recorded</span>
                <time>{date(selected.created_at)}</time>
              </div>
              <div>
                <span>Row hash</span>
                <code>{selected.row_hash}</code>
              </div>
              <div>
                <span>Prev hash</span>
                <code>{selected.prev_hash || "Genesis"}</code>
              </div>
            </div>

            {selectedRules && selectedRules.length > 0 && (
              <div className="drawer-rules">
                <div className="eyebrow">P01–P11 POLICY EVALUATION</div>
                <div className="rule-list">
                  {selectedRules.map((rule) => (
                    <div className="rule-result" key={rule.id}>
                      <span
                        className={`rule-icon ${rule.status.toLowerCase()}`}
                      >
                        {rule.status === "PASS" ? (
                          <BadgeCheck size={15} aria-hidden="true" />
                        ) : (
                          <CircleAlert size={15} aria-hidden="true" />
                        )}
                      </span>
                      <div>
                        <b>
                          {rule.id} · {rule.name}
                        </b>
                        <p>{rule.message}</p>
                      </div>
                      <em>{rule.status}</em>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="drawer-json">
              <div className="eyebrow">EVENT PAYLOAD</div>
              <pre>{JSON.stringify(selected.details, null, 2)}</pre>
            </div>
          </aside>
        )}
      </div>
    </>
  );
}
