import { useState } from "react";
import {
  Activity,
  BadgeCheck,
  CircleAlert,
  Play,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import {
  api,
  type AttackItem,
  type AttackResult,
  type ChallengeStats,
  type EvalResults,
} from "./api";
import type { Action } from "./domain";
import { Empty, PageTitle } from "./ui";

const RULE_GROUPS: { title: string; rules: string[] }[] = [
  { title: "P01 · Authority & Lifecycle", rules: ["P01"] },
  { title: "P02–P03 · Budget & Transaction Cap", rules: ["P02", "P03"] },
  { title: "P04–P05 · Merchant & Category", rules: ["P04", "P05"] },
  { title: "P06 · Canonical Quote & Currency", rules: ["P06"] },
  {
    title: "P07–P11 · Velocity, Replay & Recurring",
    rules: ["P07", "P08", "P10", "P11"],
  },
  { title: "Cart Hash Binding", rules: ["CART_HASH_BINDING"] },
];

export function Challenge({
  attacks,
  stats,
  evals,
  working,
  action,
}: {
  attacks: AttackItem[];
  stats: ChallengeStats;
  evals: EvalResults | null;
  working: boolean;
  action: Action;
}) {
  const [resultsById, setResultsById] = useState<Record<string, AttackResult>>(
    {},
  );

  async function runSingle(attackId: string) {
    await action(async () => {
      const res = await api.runAttack(attackId);
      setResultsById((prev) => ({ ...prev, [attackId]: res }));
    }, `Attack "${attackId}" evaluated by policy.`);
  }

  async function runAll() {
    await action(async () => {
      const res = await api.runAllAttacks();
      const mapped: Record<string, AttackResult> = {};
      for (const item of res.results) mapped[item.attack_id] = item;
      setResultsById(mapped);
    }, "All 15 Break-the-Mandate scenarios evaluated.");
  }

  return (
    <>
      <PageTitle
        eyebrow="ADVERSARIAL TESTING"
        title="Break the Mandate"
        detail="Run scripted adversarial carts directly against the policy engine. No PayPal call is ever made unless a verdict is APPROVE."
        action={
          <button
            className="button-dark"
            aria-label={`Run all ${attacks.length} attacks`}
            disabled={working || attacks.length === 0}
            onClick={() => void runAll()}
          >
            <Play size={16} /> <span>Run all {attacks.length} attacks</span>
          </button>
        }
      />

      <div className="challenge-counters">
        <div className="counter-card">
          <span>Attempts</span>
          <strong>{stats.attempts}</strong>
        </div>
        <div className="counter-card">
          <span>Breaches</span>
          <strong className={stats.breaches > 0 ? "status-text-bad" : "status-text-ok"}>
            {stats.breaches > 0 ? (
              <>
                <CircleAlert size={18} aria-hidden="true" /> {stats.breaches} breached
              </>
            ) : (
              <>
                <ShieldCheck size={18} aria-hidden="true" /> 0 breached
              </>
            )}
          </strong>
        </div>
        <div className="counter-card">
          <span>Blocked</span>
          <strong>{Math.max(0, stats.attempts - stats.breaches)}</strong>
        </div>
      </div>

      <div className="challenge-groups">
        {RULE_GROUPS.map((group) => {
          const items = attacks.filter((a) =>
            group.rules.includes(a.expected_rule),
          );
          if (!items.length) return null;
          return (
            <section className="panel challenge-group" key={group.title}>
              <div className="panel-heading">
                <h2>{group.title}</h2>
                <span className="count-chip">{items.length} scenarios</span>
              </div>
              <div className="attack-grid">
                {items.map((atk) => {
                  const res = resultsById[atk.id];
                  return (
                    <div className="attack-card" key={atk.id}>
                      <div className="attack-card-head">
                        <strong>{atk.title}</strong>
                        <span className="count-chip">{atk.expected_rule}</span>
                      </div>
                      <p>{atk.description}</p>
                      <div className="attack-card-foot">
                        <button
                          className="button-outline"
                          disabled={working}
                          onClick={() => void runSingle(atk.id)}
                        >
                          <ShieldAlert size={14} /> Run attack
                        </button>
                        {res && (
                          <span
                            className={`attack-outcome ${res.breached ? "bad" : "ok"}`}
                          >
                            {res.breached ? (
                              <>
                                <CircleAlert size={14} aria-hidden="true" />{" "}
                                BREACH (APPROVE)
                              </>
                            ) : (
                              <>
                                <BadgeCheck size={14} aria-hidden="true" />{" "}
                                Blocked by {res.actual_rule}
                              </>
                            )}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>

      <section className="panel eval-panel">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">OFFLINE BENCHMARK</div>
            <h2>Policy Evaluation Summary</h2>
          </div>
          <span className="synthetic-badge">
            <Activity size={14} aria-hidden="true" />
            {evals?.label ?? "Synthetic: scripted scenarios written by the author"}
          </span>
        </div>

        {evals ? (
          <>
            {evals.attack_coverage && (
              <p className="eval-coverage">
                <strong>{evals.attack_coverage}:</strong>{" "}
                {evals.attack_kinds.join(", ")}
              </p>
            )}
            <div className="eval-metrics">
              <div className="eval-stat">
                <span>Attacks blocked (N={evals.sample_size.attack_scenarios})</span>
                <strong>{evals.summary.attacks_blocked}</strong>
              </div>
              <div className="eval-stat">
                <span>False positives (N={evals.sample_size.legitimate_purchases})</span>
                <strong>{evals.summary.false_positives}</strong>
              </div>
              <div className="eval-stat">
                <span>Escalate on legitimate</span>
                <strong>{evals.summary.escalate_on_legitimate}</strong>
              </div>
              <div className="eval-stat">
                <span>Engine latency</span>
                <strong>
                  p50 {evals.latency_ms.p50} ms · p95 {evals.latency_ms.p95} ms
                </strong>
              </div>
            </div>
            {evals.escalated_legitimate_scenarios.length > 0 && (
              <details className="eval-escalations">
                <summary>
                  Why {evals.escalated_legitimate_scenarios.length} legitimate
                  scenarios escalated (human review)
                </summary>
                <ul>
                  {evals.escalated_legitimate_scenarios.map((item) => (
                    <li key={item.scenario}>
                      <code>{item.scenario}</code> ({item.product_id}):{" "}
                      {item.reasons.join("; ")}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        ) : (
          <Empty
            icon={<Activity />}
            title="No benchmark snapshot loaded"
            copy="Run python scripts/run_evals.py to generate eval_results.json."
          />
        )}
      </section>
    </>
  );
}

