# Mandate Demo Video Script (Target: Under 2:50)

## Pre-Recording Checklist
- [ ] Click **Reset** in the topbar (`PUBLIC_DEMO=true`) so you start with a fresh `$500.00` grant and clean counters.
- [ ] Wake the hosted Render app beforehand (open `/` and wait for `/api/health` + initial session load) so there is no cold-start delay.
- [ ] Close all unrelated browser tabs, extensions, and OS notifications.
- [ ] Hide `.env` files, API keys, terminal history with credentials, and personal bookmarks bar.
- [ ] Record without copyrighted background music (clean voiceover + subtle UI clicks only).

> **Fallback line if the Groq LLM is rate-limited and the yellow rules-planner banner appears:**
> *"Because GroqCloud is temporarily unavailable here, Mandate automatically fell back to its labeled deterministic rules planner (`llm_fallback=true`)—and notice every cart still passes through the exact same `P01`–`P11` policy engine."*

---

## Timed Script

### `0:00 – 0:20` | Problem & One-Liner
- **On-screen action**: Start on the **Overview** screen showing the `$500.00` wallet card and 3-step strip (`01 Grant`, `02 Agent buys`, `03 When something goes wrong`).
- **Voiceover**: *"AI shopping agents can browse and build carts, but handing an LLM an open payment credential means one prompt injection or hallucinated item can drain an account. Mandate puts a deterministic spending boundary between the AI agent and PayPal."*

### `0:20 – 1:00` | Grant (One-Time `$1.00` Vault Approval) & Autonomous Agent Buy
- **On-screen action**:
  1. In **Overview -> Spending Grant**, highlight the `$500` budget, `$400` per-purchase cap, `demo-merchant`, and `160 cm` desk width constraint; show **Enable Autonomous (vaulted)** (or pre-completed `$1.00` vault grant + auto-refund status `GRANTED`).
  2. Switch to **Proposals**, run the shopping agent on *"Find a desk that meets my approved width requirement"* -> `APPROVE` verdict, `$349.00` reserved.
  3. Open **Payments** and click **Charge vaulted PayPal** -> status updates to `CAPTURED` with no buyer redirect.
- **Voiceover**: *"First, the human sets a `$500` grant with a `$400` cap and a one-time `$1` PayPal Vault setup that immediately auto-refunds. Once granted, the shopping agent proposes a `$349` 160-cm desk, passes `P01`–`P11` with a bound `cart_hash`, and executes autonomously via PayPal `vault_id`."*

### `1:00 – 1:40` | Break the Mandate (Live Attack Blocks & `0` Breaches Counter)
- **On-screen action**: Open **Challenge (Break the Mandate)**, click **Run all 15 attacks**, and scroll past `P02–P03` (over budget/cap), `P04–P05` (lookalike merchant / gift card), and `CART_HASH_BINDING` (cart swap) showing green `Blocked by ...` badges and **`0 breached`** counter.
- **Voiceover**: *"Next, let's try to break it. Running all 15 scripted attacks—over-budget carts, lookalike merchants, mislabeled gift cards, currency swaps, and post-approval cart tampering—blocks every single attempt deterministically before PayPal is ever called: 15 blocked, 0 breaches, 0 payment rows created."*

### `1:40 – 2:10` | Ambiguity Gate Escalates & Human Approves
- **On-screen action**: Open **Proposals**, click preset **`02 Missing specification`** (`desk-unknown`), show the amber **`ESCALATE`** badge on `P09` (`Missing: desk-unknown.width_cm`), then click **Approve this proposal** to release it into `APPROVED`.
- **Voiceover**: *"What if a listing is ambiguous? When a desk omits its width, `P09` refuses to guess and escalates to the human with the exact missing attribute. Only after explicit human review against the bound `cart_hash` does it move forward."*

### `2:10 – 2:35` | Flag a Wrong Purchase & Accept a Bounded Partial Refund
- **On-screen action**: Open **Recovery**, select the captured `$349.00` payment, enter evidence (*"Wrong desk width delivered"*), click **Suggest cause (advisory)**, calculate the offer (`$314.10`), and click **Accept offer** -> status updates to `REFUNDED`, and open **Ledger** showing `Chain verified`.
- **Voiceover**: *"If a seller ships the wrong item, the human opens a Recovery case. AI can suggest a cause, but deterministic policy bands cap the refund at `$314.10`, execute it via PayPal, and record everything in our SHA-256 hash-chained audit ledger."*

### `2:35 – 2:50` | Synthetic Evaluation Numbers & Repo Link
- **On-screen action**: Flash the **Policy Evaluation Summary** panel on **Challenge** (`Synthetic: scripted scenarios written by the author`, `8 attack kinds, 50 variants`, `50 of 50 blocked`, `0 of 50 false positives`, `<1 ms` p50) and finish on the README / GitHub URL card.
- **Voiceover**: *"In our offline synthetic benchmark—labeled clearly as author-scripted scenarios—50 of 50 attacks were blocked with 0 false positives at sub-millisecond policy latency. Check out the repo and try the live sandbox demo yourself."*
