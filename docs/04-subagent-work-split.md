# Subagent work split

This plan was drafted before implementation. Subagent execution started October 28, 2026 after the user authorized the build. Actual model assignments and results are in [implementation status](08-implementation-status.md). Task IDs refer to the [build plan](03-build-plan.md).

## Team shape

Use one coordinator and at most three active workers. The roles below are reusable assignments, not six workers that must run together. Begin with fewer workers when contracts or dependencies are unsettled. The application itself uses one shopping agent and a bounded recovery model call; the coding team structure does not imply a runtime agent swarm.

The coordinator owns the integrated result, task order, shared contracts, and release evidence. Workers own bounded changes. A verification worker assesses the integrated behavior independently of its authors. This adapts the planner, builder, and evaluator separation described in [Anthropic's March 2026 application-development study](https://www.anthropic.com/research/harness-design-long-running-apps).

## Ownership map

All paths below are proposed future paths, not existing application files.

| Role | Tasks | Exclusive write area | Must deliver | Must not change independently |
| --- | --- | --- | --- | --- |
| Coordinator | T01, T08, T09; integrate all tasks | Root config, dependency manifests/locks, migrations, shared API contracts, CI, deployment, planning index | Runnable baseline, contract versions, ordered merges, release evidence | Product scope or monetary rules without recording the decision |
| Policy worker | T02 | `apps/api/mandate/grants/`, `policy/`, `catalog/`, `audit/`, and matching tests | Scoped grants, rules, reservation contract, quote/hash rules, audit behavior | PayPal adapter, UI, or shared migrations |
| Payments worker | T00, T03; adapter support for T06 | `apps/api/mandate/payments/`, `webhooks/`, `jobs/`, and matching tests | Redacted feasibility evidence, durable operations, capture/refund adapter, reconciliation | Policy outcomes, refund business bands, or frontend |
| UI worker | T04; T06 case screens | `apps/web/src/` and UI-specific tests | Grant, proposal, ledger, attack, and recovery views with real error states | Server policy, API definitions, or global dependencies without coordination |
| AI/recovery worker | T05, T06 | `apps/api/mandate/agents/`, `recovery/`, and matching tests | Restricted model tools, evidence assembly, offer calculation, human acceptance | Raw provider calls or payment accounting |
| Verification worker | T07; release verification | `tests/acceptance/`, `tests/adversarial/`, and evidence reports | Reproducible failure cases, browser results, integration verdict | Product implementation or acceptance criteria to make a failure disappear |

The policy worker exposes reservation behavior through an agreed service contract; the payment worker calls it rather than editing grant accounting. The recovery worker uses the payment worker's refund interface. The coordinator owns schema changes because all these modules share a database.

## Work waves

| Wave | Coordinator | Worker slots | Integration condition |
| --- | --- | --- | --- |
| A: feasibility and baseline | Establish repository and contracts | Payments proves T00; other slots stay idle or prepare bounded fixtures | T00 outcome recorded and T01 contracts accepted |
| B: policy and purchase | Review shared schemas and integrate small changes | Policy builds T02; payments prepares T03 adapter; UI starts T04 | Policy/reservation contract lands before final checkout wiring |
| C: complete purchase | Integrate T03 and resolve boundaries | Payments completes T03; UI wires T04; AI/recovery builds T05 | One live browser-to-provider purchase works |
| D: recovery | Own migrations and cross-module integration | AI/recovery builds T06; UI adds case screens; payments supports refund behavior | Human-approved refund works end to end |
| E: verify and ship | Prepare T08/T09 | Independent verifier runs T07; original owners fix assigned defects in available slots | All required checks pass on the merged revision |

Do not split a single budget transaction or state-machine change across competing writers. Keep strongly coupled accounting work sequential. Assign read-only review in parallel when implementation ownership would overlap.

## Dispatch contract

Every assignment must contain these fields before a worker starts:

| Field | What the coordinator supplies |
| --- | --- |
| Objective | One observable outcome and its task ID |
| Starting point | Base revision, workspace/worktree, and relevant current state |
| Read set | This index, relevant architecture sections, the interface definition, and the owned module |
| Write set | Explicit directories and any shared-file owner |
| Dependencies | What is merged, what is pending, and which fixtures may stand in temporarily |
| Acceptance | Named behavior checks and required evidence |
| Limits | No scope expansion, no deployment, no secret copying, and no unrequested workers |
| Stop condition | Finish the bounded task, or report the precise blocked dependency with evidence |
| Return format | Summary, revision/diff, touched files, checks, failures, and next integration action |

Clear task objectives, outputs, tools, and boundaries are directly supported by [Anthropic's multi-agent research report](https://www.anthropic.com/research/multi-agent-research-system). The exact file ownership and worker cap here are project choices.

## First dispatch briefs

**Payments worker, T00.** Prove the controlled merchant's sandbox saved-method purchase and refund flow. Read the build gate and PayPal references. Return the accepted request shapes and redacted operation evidence. Stop after the half-day investigation if vault permission remains unresolved and recommend the documented buyer-approval fallback. Do not build a general payment framework.

**Policy worker, T02.** Implement P01-P11 after T01 is merged, using trusted fixtures and PostgreSQL. Show that two $300 proposals under a $500 grant cannot both reserve. Demonstrate revoked grants, quote mismatch, missing attributes, duplicate intent, and velocity behavior. Return the reservation interface for T03.

**UI worker, T04.** Build the grant, purchase, and ledger journey against the frozen contracts. Include denied, escalated, pending, unknown, and refund states. Fixtures must be labeled and replaceable. Completion requires the live API journey and browser evidence, not screenshots alone.

**AI/recovery worker, T05 then T06.** First deliver the shopping tool allowlist and structured proposal flow. After checkout works, add evidence review and frozen refund offers. The model can suggest a cause but cannot authorize a payment or refund. Demonstrate that human acceptance and merchant policy still constrain injected refund instructions.

**Verification worker, T07.** Independently execute the validation matrix against the integrated revision. Start from the written acceptance criteria rather than the builders' success summaries. For every failure, return expected behavior, actual behavior, reproduction steps, and redacted evidence. Do not edit production code during review.

## Context, cost, and handoff discipline

Load only the documents and files needed for the assigned task. Keep durable notes in one task-specific file; only the coordinator updates the shared progress index. A worker returns a concise summary with links to evidence instead of pasting its entire transcript. This follows the repository-navigation approach in [OpenAI's harness engineering report](https://openai.com/index/harness-engineering/).

Timebox exploratory subtasks. After two attempts fail for the same external reason, report what changed and what dependency is missing instead of repeating the same attempt. Do not spawn nested workers by default. Use the configured model unless a specific task needs a measured capability improvement; model brand is not a responsibility boundary.

Each implementation worker should use an isolated branch/worktree from the same accepted baseline. Distinct worktrees still need distinct local ports and database schemas. Do not share development grant IDs or webhook test records across workers. Shared sandbox setup has one payments owner.

End each task with the base and final revision, files changed, contract changes, commands/checks and actual results, known risks, and the next action. Leave unfinished work labeled unfinished. The coordinator reviews the diff, runs relevant checks on the merged revision, and updates the task status. Approval of a worker's summary alone is not integration evidence.

The human owner resolves product scope, account access, spending, and publication. Routine reversible implementation decisions stay with the coordinator. Workers report blocked dependencies while continuing useful authorized work that does not depend on them.
