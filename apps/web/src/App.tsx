import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { api } from "./api";
import {
  Activity,
  Compass,
  House,
  ArrowUpRight,
  BadgeCheck,
  CircleAlert,
  FileClock,
  RotateCcw,
  ShieldAlert,
  ShoppingBag,
  WalletCards,
} from "lucide-react";
import { activeGrants, type View } from "./domain";
import { useDashboard } from "./useDashboard";
import { Login } from "./Login";
import { Overview } from "./Overview";
import { GuidedDemo } from "./GuidedDemo";
import { Proposals } from "./Proposals";
import { Challenge } from "./Challenge";
import { Payments } from "./Payments";
import { Recovery } from "./Recovery";
import { Ledger } from "./Ledger";
function checkoutReturn() {
  const path = window.location.pathname.replace(/\/$/, "");
  if (path === "/payments/success") return "approved";
  if (path === "/payments/cancel" || path === "/payments/cancelled")
    return "cancelled";
  return new URLSearchParams(window.location.search).get("checkout");
}
const iconMap = {
  overview: House,
  guide: Compass,
  proposals: ShoppingBag,
  challenge: ShieldAlert,
  payments: WalletCards,
  recovery: RotateCcw,
  ledger: FileClock,
} satisfies Record<View, typeof Activity>;
const views: { id: View; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "guide", label: "Guide" },
  { id: "proposals", label: "Proposals" },
  { id: "challenge", label: "Challenge" },
  { id: "payments", label: "Payments" },
  { id: "recovery", label: "Recovery" },
  { id: "ledger", label: "Ledger" },
];
export default function App() {
  const callback = checkoutReturn();
  const callbackOrderId =
    callback === "approved"
      ? new URLSearchParams(window.location.search).get("token")
      : null;
  const [view, setViewState] = useState<View>(() =>
    callback ? "payments" : "overview",
  );
  const [selectedGrantId, setSelectedGrantId] = useState("");
  const [agentFallbackRun, setAgentFallbackRun] = useState<{
    planner: string;
    summary: string;
  } | null>(null);
  const viewTransition = useRef<ViewTransition | null>(null);
  const requestedView = useRef(view);
  function setView(next: View) {
    if (requestedView.current === next) return;
    requestedView.current = next;
    viewTransition.current?.skipTransition();
    if (
      !document.startViewTransition ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      setViewState(next);
      window.scrollTo({ top: 0, behavior: "instant" });
      return;
    }
    viewTransition.current = document.startViewTransition(() => {
      if (requestedView.current === next) {
        flushSync(() => setViewState(next));
        window.scrollTo({ top: 0, behavior: "instant" });
      }
    });
    // Interrupted transitions reject readiness while the view update continues.
    void viewTransition.current.ready.catch(() => {});
  }

  const { state, notice, setNotice, working, action, refresh, logout, now } =
    useDashboard(
      callback === "approved"
        ? {
            kind: "info",
            text: "Returned from checkout. This URL does not confirm approval or capture. Review the stored order and provider status below.",
          }
        : callback === "cancelled"
          ? {
              kind: "info",
              text: "Returned from cancelled checkout. The reservation remains until the provider outcome is reconciled.",
            }
          : null,
    );
  if (state.kind === "locked") return <Login onLogin={refresh} />;
  if (state.kind === "loading")
    return (
      <main className="loading-screen" aria-busy="true">
        <div className="brand-mark">M</div>
        <p>Opening your ledger…</p>
      </main>
    );
  if (state.kind === "error")
    return (
      <main className="loading-screen">
        <CircleAlert size={28} />
        <h1>Mandate could not connect</h1>
        <p role="alert">{state.text}</p>
        <button
          className="button-dark"
          disabled={working}
          onClick={() => void refresh()}
        >
          Try again
        </button>
      </main>
    );
  const {
    session,
    products,
    mandates,
    proposals,
    payments,
    cases,
    ledger,
    verify,
    attacks,
    challengeStats,
    evals,
  } = state.data;
  const usableGrants = activeGrants(mandates, now);
  const currentGrant =
    usableGrants.find((grant) => grant.id === selectedGrantId) ??
    usableGrants[0] ??
    null;
  return (
    <div className="app-shell">
      <aside className="rail">
        <a
          className="brand"
          href="#overview"
          onClick={() => setView("overview")}
          aria-label="Mandate home"
        >
          <span className="brand-mark">M</span>
          <span>
            mandate<small>SPENDING CONTROL</small>
          </span>
        </a>
        <div className="rail-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {views.map((item) => {
            const Icon = iconMap[item.id];
            return (
              <button
                key={item.id}
                className={`nav-item ${view === item.id ? "selected" : ""}`}
                onClick={() => setView(item.id)}
                aria-current={view === item.id ? "page" : undefined}
              >
                <Icon size={17} aria-hidden="true" />
                <span>{item.label}</span>
                {item.id === "recovery" &&
                  cases.some((c) => c.status === "PROPOSED") && <i />}
              </button>
            );
          })}
        </nav>
        <div className="rail-footer">
          <div className="avatar">LW</div>
          <div>
            <strong>Local workspace</strong>
            <span>Session scoped</span>
          </div>
          <span className="live-dot" aria-label="Connected" />
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <a
            className="mobile-brand"
            href="#overview"
            onClick={() => setView("overview")}
            aria-label="Mandate home"
          >
            <span className="brand-mark">M</span>mandate
            <span className="sandbox-label">Sandbox</span>
          </a>
          <div className="breadcrumb">
            Workspace <span>/</span>{" "}
            <b>{views.find((v) => v.id === view)?.label}</b>
          </div>
          <div className="top-actions">
            <span className="mode-chip">
              <span />
              {session.public_demo
                ? "Public demo (isolated)"
                : session.access_required
                  ? "Protected workspace"
                  : "Local workspace"}
            </span>
            <button
              className="icon-button"
              aria-label="Refresh data"
              disabled={working}
              onClick={() => void refresh()}
            >
              <RotateCcw size={16} />
            </button>
            {session.public_demo && (
              <button
                className="button-quiet"
                disabled={working}
                onClick={() =>
                  void action(async () => {
                    const next = await api.resetSession();
                    setSelectedGrantId("");
                    return next;
                  }, "Demo workspace reset with a fresh $500 spending grant.")
                }
              >
                Reset
              </button>
            )}
            {session.access_required && (
              <button
                className="button-quiet"
                disabled={working}
                onClick={() => void logout()}
              >
                Log out
              </button>
            )}
          </div>
        </header>
        {!session?.paypal_configured && (
          <div className="provider-banner">
            <span className="banner-icon">
              <CircleAlert size={16} />
            </span>
            <div>
              <strong>PayPal is not configured</strong>
              <span>
                Policy checks and reservations are live. Checkout, capture and
                refunds are unavailable until PayPal is set up; the shopping
                agent also needs a model key.
              </span>
            </div>
            <a href="#payments" onClick={() => setView("payments")}>
              Setup status <ArrowUpRight size={14} />
            </a>
          </div>
        )}
        {notice && (
          <div
            className={`notice ${notice.kind}`}
            role={notice.kind === "error" ? "alert" : "status"}
          >
            <span>
              {notice.kind === "error" ? (
                <CircleAlert size={16} />
              ) : (
                <BadgeCheck size={16} />
              )}
            </span>
            {notice.text}
            <button
              aria-label="Dismiss notification"
              onClick={() => setNotice(null)}
            >
              ×
            </button>
          </div>
        )}
        <nav className="flow-strip" aria-label="Mandate workflow steps">
          <button
            type="button"
            className={`flow-step ${view === "overview" ? "current" : ""}`}
            onClick={() => setView("overview")}
          >
            <span>01</span>
            <div>
              <strong>Grant</strong>
              <small>Budget, cap &amp; vault mode</small>
            </div>
          </button>
          <button
            type="button"
            className={`flow-step ${view === "proposals" || view === "payments" ? "current" : ""}`}
            onClick={() => setView("proposals")}
          >
            <span>02</span>
            <div>
              <strong>Agent buys</strong>
              <small>P01–P11 policy &amp; PayPal execution</small>
            </div>
          </button>
          <button
            type="button"
            className={`flow-step ${view === "recovery" ? "current" : ""}`}
            onClick={() => setView("recovery")}
          >
            <span>03</span>
            <div>
              <strong>When something goes wrong</strong>
              <small>Bounded recovery &amp; audit ledger</small>
            </div>
          </button>
        </nav>
        {agentFallbackRun && (
          <div className="provider-banner fallback-banner" role="status">
            <span className="banner-icon">
              <CircleAlert size={16} aria-hidden="true" />
            </span>
            <div>
              <strong>{agentFallbackRun.planner}</strong>
              <span>
                Deterministic catalog fallback was used (llm_fallback=true):{" "}
                {agentFallbackRun.summary}
              </span>
            </div>
            <button
              type="button"
              className="button-quiet"
              onClick={() => setAgentFallbackRun(null)}
            >
              Dismiss
            </button>
          </div>
        )}
        <div className="view-content">
          {view === "overview" && (
            <Overview
              grant={currentGrant}
              mandates={mandates}
              activeGrants={usableGrants}
              selectGrant={setSelectedGrantId}
              proposals={proposals}
              payments={payments}
              cases={cases}
              ledger={ledger}
              verify={verify}
              setView={setView}
              working={working}
              action={action}
              createGrant={async (body) => {
                const created = await api.createMandate(body);
                setSelectedGrantId(created.id);
              }}
              paypalConfigured={Boolean(session?.paypal_configured)}
              vaultAutonomyVerified={Boolean(session?.vault_autonomy_verified)}
            />
          )}
          {view === "guide" && (
            <GuidedDemo
              grant={currentGrant}
              proposals={proposals}
              payments={payments}
              cases={cases}
              paypalConfigured={Boolean(session?.paypal_configured)}
              working={working}
              action={action}
              createGrant={async (body) => {
                const created = await api.createMandate(body);
                setSelectedGrantId(created.id);
              }}
              onAgentResult={(res) =>
                setAgentFallbackRun(
                  res.llm_fallback
                    ? {
                        planner:
                          res.planner_label ?? "Rules planner, LLM unavailable",
                        summary: res.summary,
                      }
                    : null,
                )
              }
              setView={setView}
            />
          )}
          {view === "proposals" && (
            <Proposals
              grant={currentGrant}
              mandates={mandates}
              now={now}
              setView={setView}
              products={products}
              proposals={proposals}
              working={working}
              action={action}
              onAgentResult={(res) =>
                setAgentFallbackRun(
                  res.llm_fallback
                    ? {
                        planner:
                          res.planner_label ?? "Rules planner, LLM unavailable",
                        summary: res.summary,
                      }
                    : null,
                )
              }
            />
          )}
          {view === "challenge" && (
            <Challenge
              attacks={attacks}
              stats={challengeStats}
              evals={evals}
              working={working}
              action={action}
            />
          )}
          {view === "payments" && (
            <Payments
              payments={payments}
              proposals={proposals}
              mandates={mandates}
              now={now}
              working={working}
              action={action}
              configured={Boolean(session?.paypal_configured)}
              vaultAutonomyVerified={Boolean(session?.vault_autonomy_verified)}
              callbackOrderId={callbackOrderId}
            />
          )}
          {view === "recovery" && (
            <Recovery
              cases={cases}
              payments={payments}
              configured={session.paypal_configured}
              working={working}
              action={action}
            />
          )}
          {view === "ledger" && (
            <Ledger entries={ledger} verify={verify} proposals={proposals} />
          )}
        </div>
      </main>
    </div>
  );
}
