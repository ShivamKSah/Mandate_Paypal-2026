import { FileClock, ShieldCheck } from "lucide-react";
import { type LedgerEntry, type LedgerVerify } from "./api";
import { date } from "./domain";
import { PageTitle, Empty } from "./ui";
export function Ledger({
  entries,
  verify,
}: {
  entries: LedgerEntry[];
  verify: LedgerVerify | null;
}) {
  return (
    <>
      <PageTitle
        eyebrow="AUDIT TRAIL"
        title="Decision ledger"
        detail="Append-only events record policy outcomes, reservations and provider activity for this session."
        action={
          verify && (
            <span
              className={`verification ${verify.valid ? "verified" : "invalid"}`}
            >
              <ShieldCheck size={16} />
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
      <section className="panel ledger-table">
        <div className="ledger-table-head">
          <span>EVENT</span>
          <span>ENTITY</span>
          <span>RECORDED</span>
          <span>CHAIN HASH</span>
        </div>
        {entries.length ? (
          entries.map((row) => (
            <details className="ledger-event" key={row.id}>
              <summary>
                <span className="event-title">
                  <i className="ledger-dot" />
                  {row.event_type.replaceAll("_", " ")}
                </span>
                <code>{row.entity_id}</code>
                <time>{date(row.created_at)}</time>
                <code>{row.row_hash.slice(0, 16)}…</code>
              </summary>
              <div className="event-details">
                <b>Event details</b>
                <pre>{JSON.stringify(row.details, null, 2)}</pre>
                <div>
                  Previous hash · <code>{row.prev_hash || "Genesis"}</code>
                </div>
              </div>
            </details>
          ))
        ) : (
          <Empty
            icon={<FileClock />}
            title="Ledger is empty"
            copy="The first grant or policy decision will establish a verifiable event history."
          />
        )}
      </section>
    </>
  );
}
