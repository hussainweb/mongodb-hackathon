# Agents in Context Toronto — Project Options & Track Alignment

A decision brief comparing candidate project directions for our 2-person, 1-day sprint (~6h15m: 10:45 AM – 5:00 PM ET).

## Hackathon Constraints & Judging Criteria

- **Event & Schedule (Nov 14, The Quay, Toronto):** 9:00 AM Doors & team formation · **10:45 AM** Hacking begins · **5:00 PM** Submissions due · **5:15–6:45 PM** Round 1 judging · **7:00 PM** Final round (Top 6 teams) · **8:15 PM** Winners announced. *(See [hackathon-resource-guide.md](hackathon-resource-guide.md) for all official links and credit redemption steps.)*
- **Mandatory Infrastructure:** MongoDB Atlas Sandbox (`Cluster0`, Dedicated M10, MongoDB 9.0.7 — supports Search, Vector Search, Automated Embeddings, Change Streams, JSON Schema validation). Original work only, public GitHub repo, accessible demo link, up to 4 team members, 1-minute submission video (showing code & functionality, verify video + audio playback) + concise project description on Cerebral Valley (ensure all team members are added) + 3-minute live in-person demo.
- **Strictly Prohibited (Instant DQ):** Streamlit apps, basic RAG apps, dashboard-as-main-feature, AI job application screeners, image analyzers, mental health/medical/nutrition/education/personality/sports analyzers.
- **Round 1 Judging:** **35%** Technical Demo · **30%** Implementation Difficulty · **20%** Impact · **15%** Creativity *(Round 2 top 6: 25% each)*.
- **Prizes & Partner Credits:**
  - *Prizes:* 1st ($7k MongoDB + $3k LangSmith + 3 mo ElevenLabs Pro), 2nd ($5k MongoDB + $2k LangSmith), 3rd ($3k MongoDB + $1k LangSmith), plus **Best Project Built with ElevenLabs** (3 mo Scale Tier).
  - *Hacker Credits:* **Voyage AI** 200M free tokens (add payment method for Tier 1 rate limits), **ElevenLabs** 1 mo Creator / 131k credits (Discord `#coupon-codes`), **LangSmith** $50 credits + Deployments (Airtable form).
- **Planned Core Stack:** Python 3.14, FastAPI + minimal HTMX/SSE live operator theater (no heavy SPA/CSS time sink), MongoDB Atlas, Pydantic AI + Logfire, LangSmith tracing/evals, Voyage AI embeddings/reranking (or Atlas Automated Embeddings), and a targeted ElevenLabs voice hook.

---

## The Three Official Tracks

1. **Agents You Can Audit** — Atlas identity/policy/audit layer (collections, JSON Schema validation, Change Streams): enforce policy *before* action, reconstruct why/under whose authority an action ran, and stop or roll back mid-run.
2. **Memory You Can Govern** — Atlas + Vector Search: scoped ACLs so client/team memory never leaks, TTL/forgetting/correction of wrong or expired memory, and proof that memory *changed behavior* rather than just stuffing prompts.
3. **Finish the Job** — Atlas verified task state + Vector Search past experience: distinguish *only-sent* vs. *actually took-effect*, crash-resumable checkpoints without full replay, and mid-run adaptation when schemas/fields/workflows drift.

---

## Primary Options (Real Data / Targets in <30 Min + High Novelty)

These four options avoid inventing contrived synthetic enterprise datasets and avoid looking like a standard "AI agent wrapper." Each centers on one primary track while naturally weaving in mechanics from the other two.

### Option 1: "Terraform `plan / apply / destroy` for AI Agents" — Auditable Execution Proxy with Time-Travel Rollback

- **Primary Track:** Track 1 (*Agents You Can Audit*) · *Crosses into Track 3 (post-effect verification)*
- **Problem Statement:** AI agents fail in production not because they can't reason, but because they have no pre-execution `sudo` gate and no `Ctrl+Z` rollback when a multi-step run goes wrong mid-flight.
- **What the Solution Looks Like:**
  - **What we actually build & run:** (1) A **FastAPI + HTMX/SSE web app** acting as the operator console & policy proxy, (2) a **Pydantic AI agent** whose tools all go through our Atlas-backed proxy instead of calling APIs directly, (3) **2–3 real local/live targets** (a real test GitHub repo, a local FastAPI feature-flag/config service, and a local workspace/Docker container), and (4) **MongoDB Atlas** (`Cluster0`) storing every intent, snapshot, and Change Stream trigger.
  - **What it looks like in the browser:**
    ```text
    +-------------------------------------------------------------------------+
    | Task: "Prepare staging hotfix release"   Principal: hussain (staging)   |
    | [ Run Agent ]   [ STOP & REWIND TO STEP 0 ]   [ Mic: Voice Sudo ]       |
    +------------------------------------+------------------------------------+
    | LIVE EXECUTION & POLICY GATE (SSE) | REAL TARGET STATE (LIVE PROBE)     |
    |                                    |                                    |
    | 1. github.create_branch            | GitHub Test Repo:                  |
    |    Gate: ALLOW -> APPLIED          |   branch: hotfix/retry-limit (NEW) |
    |    Undo saved: delete_branch       |                                    |
    |                                    | Local Config Service:              |
    | 2. config.patch(max_retries=5)     |   version: v14 -> v15              |
    |    Gate: VOICE SUDO REQUIRED       |   max_retries: 2 -> 5              |
    |    -> Spoken: "Approve staging"    |                                    |
    |    -> APPLIED                      | Prod Cache:                        |
    |                                    |   UNTOUCHED (blocked pre-action)   |
    | 3. cache.purge(env="prod")         |                                    |
    |    Gate: DENY (wrong scope)        | Logfire / LangSmith Trace: [link]  |
    +------------------------------------+------------------------------------+
    ```
  - **End-to-end flow:** You type a goal and hit **Run Agent**. Instead of blindly mutating systems, the agent proposes one tool call at a time into MongoDB `action_intents`. The proxy checks `delegations` + `policies`, snapshots `pre_state`, and registers the inverse `compensating_action`. Low-risk steps run automatically; medium/high-risk steps play an ElevenLabs voice prompt asking for your spoken `"sudo"` approval; out-of-scope steps are rejected *before* execution. Clicking **Stop & Rewind** flips a flag in MongoDB, triggers an Atlas Change Stream interrupt, executes every saved inverse action in reverse order, and shows the GitHub branch disappearing and the config service reverting to `v14`.
- **Concrete Use Case & What You See:**
  - *Scenario:* An engineer asks the agent to *"prepare a staging hotfix release"* across 3 real targets: (1) create a GitHub branch & release note commit in a test repo, (2) raise a rate-limit setting in a local FastAPI config service, and (3) attempt to purge a `prod` cache / force-push `main`.
  - *Result:* You prove pre-action blocking, who authorized each step, why it ran, and real external state reverting on demand.
- **MongoDB Data Stored:**
  - `delegations`: Human principal, role, allowed resource scopes, max auto-approved risk tier, expiry.
  - `policies`: Declarative allow / `require_voice_sudo` / deny rules enforced with MongoDB JSON Schema validation.
  - `action_intents`: One doc per tool call with `authority_chain`, `rationale`, `tool` + polymorphic `args`, `gate_decision` (+ voice transcript), `pre_state` snapshot, registered `compensating_action`, `post_state`, and `rollback.status`.
  - `runs` (watched via **Atlas Change Streams**): Live `halt_requested` and `rewind_to_step` triggers that interrupt the worker before the next step.
  - `action_precedents` (**Atlas Vector Search**): Past blocked, approved, and rolled-back intents + rationales for semantic risk gating.
- **Why MongoDB Atlas Shines Here:**
  - *Polymorphic `$jsonSchema` enforcement:* Enforces at the DB engine level that no intent can exist without `authority_chain`, `rationale`, and `compensating_action`, even though every tool's `args` and `pre_state` differ.
  - *Change Streams as kill-switch bus:* Sub-second push interrupts (`watch()` + resume tokens) halt the agent and run reverse rollbacks with zero polling.
  - *TTL indexes + ACID transactions:* Voice-approved `delegations` self-expire via native TTL indexes; multi-doc transactions prevent races between tool execution and `STOP & REWIND`.
  - *Atlas Hybrid/Vector Search (Voyage AI):* Catches innocuously phrased intents that semantically resemble past rolled-back incidents and auto-escalates them to Voice Sudo.
- **The Pitch:** Teams don't block agents because models aren't smart enough—they block them because agents have no `sudo` and no `Ctrl+Z`. Instead of building "an agent for X," this builds the auditable execution runtime wrapping any Pydantic AI agent.
- **Believable Targets (Zero Fake Data):** Drives real actions against resources we control directly: a test GitHub repository (issues/branches/PRs), local Docker containers/files, and a local DB or S3-compatible store.
- **ElevenLabs Hook:** Spoken `"sudo"` approval channel—when an agent hits a high-risk action gate, it calls out for voice confirmation before proceeding.
- **3-Minute Demo Flow:** Kick off the staging release task -> watch an unauthorized `prod` step get blocked pre-execution -> approve a gated config step by voice -> trigger mid-run halt & rewind, proving real resources revert cleanly -> inspect causal trace in Logfire/LangSmith.
- **Partner / GTM Role:** Frame the enterprise trust gap, design the risky edge-case prompts for the LangSmith eval suite, and operate the live kill/rewind controls on stage.

---

### Option 2: "The Unkillable Integrator" — Chaos-Tested API Cutover & Schema-Drift Closer

- **Primary Track:** Track 3 (*Finish the Job*) · *Crosses into Track 1 (gates/rollback) & Track 2 (fix memory)*
- **Problem Statement:** Multi-step API workflows silently break in the real world: webhooks return `202 Accepted` without actually processing, workers crash mid-run causing duplicate side effects, and downstream APIs rename fields overnight.
- **What the Solution Looks Like:**
  - **What we actually build & run:** (1) A **FastAPI + HTMX/SSE control room**, (2) a **separate Pydantic AI worker process** (so we can literally `SIGKILL` its OS PID live on stage!) checkpointing every step in MongoDB Atlas, (3) **3 tiny local FastAPI mock external services** (Auth, Webhook Dispatcher, Quota/Billing) that serve real OpenAPI specs and can be toggled from `v1` to breaking `v2` at runtime, and (4) **Atlas Vector Search** over past API drift fixes.
  - **What it looks like in the browser:**
    ```text
    +-------------------------------------------------------------------------+
    | Job: "Onboard Workspace Acme-42"   Worker PID: 48192 (ALIVE)            |
    | CHAOS: [ Drop Webhook 202 ]  [ SIGKILL Worker ]  [ Swap API v1 -> v2 ]  |
    +------------------------------------+------------------------------------+
    | VERIFIED STEP PIPELINE (SSE)       | DOWNSTREAM SERVICES & PROBES       |
    |                                    |                                    |
    | 1. auth.create_tenant              | Auth API (v1):                     |
    |    SENT -> VERIFIED TOOK EFFECT    |   tenant acme-42 exists (1x only)  |
    |                                    |                                    |
    | 2. webhook.register                | Webhook API (v2 - DRIFTED!):       |
    |    SENT (202) -> PROBE FAILED!     |   renamed url -> callback_uri      |
    |    -> Retried -> VERIFIED          |   Probe: test ping 200 OK          |
    |                                    |                                    |
    | 3. billing.set_quota               | Vector Search Recall:              |
    |    RESUMED AFTER SIGKILL -> DONE   |   Matched past OpenAPI v2 diff     |
    +------------------------------------+------------------------------------+
    ```
  - **End-to-end flow:** You launch a workspace cutover. While it runs, you click **Drop Webhook 202**—the target returns `202 Accepted`, but the agent's independent probe sees no webhook registered and retries. Next you click **SIGKILL Worker**—the worker PID actually dies on screen, you click **Restart Worker**, and it resumes at Step 3 from MongoDB without creating a duplicate tenant. Finally you click **Swap API v1 → v2**—the next call fails with `422 Unprocessable Entity`, Pydantic AI pulls the target's live `/openapi.json` + queries Atlas Vector Search for past field-rename fixes, remaps `webhook_url → callback_uri`, and finishes the job (or asks via ElevenLabs voice if an unknown required field has no safe default).
- **Concrete Use Case & What You See:**
  - *Scenario:* We run a 4-step *"New Customer Workspace Cutover"* across 3 real local FastAPI microservices (Auth Service, Webhook Dispatcher, Billing/Quota Service): create tenant -> register webhook -> enable quota -> verify live webhook delivery.
  - *Result:* Judges literally watch the OS process die, watch a lying `202` get caught, and watch an API schema change mid-flight—yet the workflow finishes cleanly with zero duplicate side effects.
- **MongoDB Data Stored:**
  - `workflow_runs` & `step_checkpoints`: Idempotency keys, `status` (`pending | sent | verified_took_effect | failed`), retry counts, external resource IDs, and probe results.
  - `api_drift_playbooks` (**Atlas Vector Search**): Past OpenAPI diffs, field-mapping rules, error signatures, and confidence scores (invalidatable if a fix turns out wrong).
  - `service_events`: Live HTTP request/response traces and verification probe evidence.
- **Why MongoDB Atlas Shines Here:**
  - *Atlas Hybrid/Vector Search (Voyage AI):* Combines exact HTTP status/endpoint filters with semantic similarity over OpenAPI `v1 -> v2` diffs so the agent matches renamed fields (`webhook_url -> callback_uri`) mid-run.
  - *ACID checkpoints:* Multi-document transactions atomically record `sent -> verified_took_effect` alongside idempotency keys so `SIGKILL` recovery never double-provisions.
  - *Schema-flexible HTTP traces + Change Streams:* Stores arbitrary drifting v1/v2 payloads without migrations and pushes live verification/adaptation state to the browser via `watch()`.
- **Believable Data / Targets:** 2–3 lightweight FastAPI/Docker mock external services with real OpenAPI `v1` and `v2` specs (renamed fields, changed auth/status codes, and a `202 Accepted` endpoint that silently drops async work). The OpenAPI specs, HTTP traces, and Atlas checkpoints *are* the data.
- **ElevenLabs Hook:** Voice escalation when the agent encounters an ambiguous breaking schema change with low confidence, asking the operator how to map the new field.
- **Partner / GTM Role:** Anchor the business pain of silent webhook/integration failures, narrate the chaos sequence, and trigger the live chaos buttons during the demo.
- **Watch-out:** Frame the story in crisp business terms so non-SRE judges feel the impact immediately.

---

### Option 3: Causal Memory Firewall — Multi-Tenant Ops Triage with Provable Memory Diffs

- **Primary Track:** Track 2 (*Memory You Can Govern*) · *Crosses into Track 1 (authority-scoped writes)*
- **Problem Statement:** AI agents with long-term memory silently leak policies across teams/clients and keep obeying stale or wrong facts even after humans correct them—and most demos can't prove memory actually changed a decision.
- **What the Solution Looks Like:**
  - **What we actually build & run:** (1) A **FastAPI + HTMX/SSE Split-Screen Policy Triage Workbench**, (2) a **Pydantic AI triage agent** backed by a single **Atlas Vector Search** collection with strict tenant ACL filters and memory lifecycle states, (3) a **seed corpus** of real GitHub repo triage policies/issues (or Toronto Open Data rules), and (4) an automated **LangSmith counterfactual eval runner** that proves `0%` cross-tenant leaks and `100%` behavior change after a memory edit.
  - **What it looks like in the browser:**
    ```text
    +-------------------------------------------------------------------------+
    | Incoming Ticket: "OAuth callback fails with 500 on token refresh"       |
    | [ Run Side-by-Side Triage ]   [ Mic: Voice Memory Governance ]          |
    +------------------------------------+------------------------------------+
    | TENANT A (Org: FastAPI)            | TENANT B (Org: Next.js)            |
    | ACL Filter: tenant="org_a"         | ACL Filter: tenant="org_b"         |
    |                                    |                                    |
    | Retrieved Memory:                  | Retrieved Memory (BEFORE EDIT):    |
    |  - [ACTIVE] Auth bugs -> @sec-team |  - [STALE] Auth -> @legacy-team    |
    | Decision: Escalate to @sec-team    | Decision: Assign @legacy-team (BAD)|
    |                                    |                                    |
    |                                    | -> Spoken: "Expire legacy-team for |
    |                                    |    Org B; use @security-triage"    |
    |                                    | Decision (AFTER EDIT):             |
    | Decision: UNCHANGED (@sec-team)    |  -> FLIPPED to @security-triage!   |
    +------------------------------------+------------------------------------+
    | LangSmith Counterfactual Proof: Leak Rate = 0% | Decision Flip = 100%   |
    +-------------------------------------------------------------------------+
    ```
  - **End-to-end flow:** You submit one real bug/support ticket and run it simultaneously through Tenant A and Tenant B. Both hit the same Atlas Vector Search collection, but strict tenant ACL filters prevent Tenant A's rules from ever appearing in Tenant B's retrieval. Tenant B routes the ticket wrong because of an outdated remembered rule. You speak a correction into ElevenLabs; the app marks the old MongoDB memory document `status: "invalidated"` and writes the new rule with authority metadata, then automatically replays the exact same ticket—showing Tenant B's routing flip immediately while Tenant A stays untouched.
- **Concrete Use Case & What You See:**
  - *Scenario:* An operations triage agent routes incoming support/issue tickets for two isolated orgs sharing one platform (e.g., **Org A: `fastapi/fastapi` vs Org B: `vercel/next.js`**, or **Ward A vs Ward B municipal rules**). Both orgs have overlapping terms ("security report", "breaking regression", "escalate to maintainer"), but opposite routing rules.
  - *Result:* You visually prove scoped isolation, instant forgetting/correction, and causal impact on agent behavior—not just RAG retrieval.
- **MongoDB Data Stored:**
  - `tenant_memories` (**Atlas Vector Search**): Memory text + embedding, strict `tenant_id` / `role_acl` filter fields, `source_authority`, `created_at`, `expires_at` (TTL), and `superseded_by` / `status` (`active | invalidated | expired`).
  - `memory_audit_log`: Who wrote, read, corrected, or expired each memory and which `run_id` consumed it.
  - `counterfactual_runs`: Before-and-after decision snapshots (`memory_snapshot_v1 -> decision_A` vs `memory_snapshot_v2 -> decision_B`) proving causal impact.
- **Why MongoDB Atlas Shines Here:**
  - *Atlas Vector Search with strict pre-filtering:* Enforces `tenant_id`, `role_acl`, and `status: "active"` *inside* the vector index query on one shared collection—preventing cross-tenant bleed by construction.
  - *Native TTL indexes + status supersession:* Time-bound rules auto-expire at the DB layer; spoken corrections flip `status: "invalidated"` and record the replacement's authority lineage cleanly.
  - *Change Streams for reactive counterfactual replay:* Watching `tenant_memories` automatically triggers re-evaluation and streams the live `BEFORE -> AFTER` decision flip to the UI.
  - *Rich nested provenance:* Stores full decision graphs, retrieved memory IDs, and LangSmith eval scores in one self-contained `counterfactual_runs` document.
- **Believable Data / Targets (Real Public Corpora):**
  - *Path A:* Real public GitHub issues/PRs and maintainer policies across 2–3 open-source repositories (each org = an isolated tenant ACL).
  - *Path B:* Real Toronto Open Data (municipal bylaws, 311 routing rules, or ward/department policies).
- **ElevenLabs Hook:** Voice-driven governance—speak *"Deprecate rule X for Org B as of today"* to invalidate/TTL a memory live and immediately watch the re-run change outcome.
- **Partner / GTM Role:** Curate real policy conflicts across tenants and build the adversarial counterfactual test cases for LangSmith.
- **Watch-out:** Must remain unmistakably distinct from "RAG + metadata filter."

---

### Option 4: Live-Feed Disruption Closer (Civic / Transit / Weather Dispatch)

- **Primary Track:** Track 3 (*Finish the Job*) · *Crosses into Track 1 (dispatch caps) & ElevenLabs*
- **Problem Statement:** During live weather or transit disruptions, alert and rerouting workflows often fire notifications blindly without verifying delivery or respecting safety/budget caps when conditions shift mid-response.
- **What the Solution Looks Like:**
  - **What we actually build & run:** (1) A **FastAPI + HTMX/SSE Dispatch Console**, (2) a **live feed poller** pulling real Environment Canada / Toronto TTC JSON alerts, (3) a **Pydantic AI dispatch coordinator** checkpointed in MongoDB Atlas, and (4) **3 local simulated notification/dispatch receivers** (Ops Console, Rider SMS Gateway, Carrier Reroute API) where one receiver can fail silently.
  - **What it looks like in the browser:**
    ```text
    +-------------------------------------------------------------------------+
    | LIVE ALERT (Environment Canada / TTC): "Line 1 Signal Issue - Bloor"    |
    | [ Trigger Live Dispatch ]   [ Simulate Channel Drop ]   [ Voice Reply ] |
    +------------------------------------+------------------------------------+
    | DISPATCH EXECUTION & VERIFICATION  | POLICY & CHANNEL RECEIVERS         |
    |                                    |                                    |
    | 1. Classify impact: 6 zones        | Policy Cap: max 3 zones auto       |
    | 2. Update detour board: VERIFIED   | -> PAUSED: ElevenLabs spoke brief: |
    | 3. Notify Ops Webhook: VERIFIED    |    "6 zones hit; approve alert?"   |
    | 4. Notify Rider SMS:               | -> Dispatcher: "Approve all 6"     |
    |    SENT (200) -> NO ACK!           |                                    |
    |    -> Fallback Email/Push: ACKED!  | Final Status: ALL CHANNELS ACKED   |
    +------------------------------------+------------------------------------+
    ```
  - **End-to-end flow:** The app pulls a real active alert (or replays today's real JSON feed). Pydantic AI generates the multi-channel dispatch plan. Because 6 zones exceed the 3-zone auto-broadcast policy cap, execution pauses before notifying riders and **ElevenLabs speaks a 10-second audio briefing** to the dispatcher, resuming once you approve by voice. When the SMS receiver accepts the HTTP request (`200 OK`) but fails the delivery-ack probe, the agent detects `only-sent` vs `took-effect`, automatically falls back to the secondary channel, and verifies all recipients received the update.
- **Concrete Use Case & What You See:**
  - *Scenario:* A live Environment Canada weather alert or Toronto TTC service disruption triggers a multi-step response: (1) classify affected zones/routes, (2) update active detour status in a local dispatch board, (3) notify 3 downstream webhook channels (ops Slack mock, rider SMS mock, partner carrier API), and (4) verify every channel actually acknowledged receipt.
  - *Result:* A vivid, non-developer real-world demo combining live public feeds, delivery verification, policy caps, and voice dispatch.
- **MongoDB Data Stored:**
  - `disruption_events`: Raw real feed snapshots (Environment Canada / TTC JSON), normalized severity, affected corridors.
  - `dispatch_runs` & `delivery_checkpoints`: Per-channel `sent` vs `verified_acked` state, retry/fallback history, crash-resume cursor.
  - `dispatch_policies`: Max auto-broadcast radius, quiet-hours / approval thresholds, operator approval records.
- **Why MongoDB Atlas Shines Here:**
  - *Zero-migration multi-source ingestion:* Environment Canada weather feeds and TTC transit alerts have totally different nested schemas—both land directly in `disruption_events` without brittle ETL tables.
  - *Native `2dsphere` geospatial + Vector Search:* Combines MongoDB geospatial queries (matching alert coordinates/corridors to affected zones) with Atlas Vector Search over past disruption responses to rank rerouting plans.
  - *Change Streams + TTL:* Watches live feed updates and voice approvals in real time (`watch()`), while TTL indexes automatically expire stale disruption alerts.
  - *`$jsonSchema` + atomic delivery checkpoints:* Enforces broadcast-cap policy invariants in the DB and tracks `only-sent (200)` vs `verified_acked` per channel.
- **Believable Data / Targets:** Live Environment Canada / OpenWeather alerts and Toronto Open Data / TTC feeds driving a local dispatch and webhook/notification target.
- **Partner / GTM Role:** Own the civic/operations narrative and live voice interaction on stage.
- **Watch-out:** Keep feed parsing minimal (1–2 clean JSON endpoints) so GTFS/feed quirks don't consume the 6-hour build budget.

---

## Earlier Domain Variations (Still on the Table if Data Is Scoped Tightly)

These three earlier variations share the same Track 3 + Track 1/2 engine and can be paired with realistic local mocks if a narrower operational story appeals more:

### Option 5: Idempotent Financial / Order Settlement Closer

- **Primary Track:** Track 3 (*Finish the Job*) + Track 1 (*Agents You Can Audit*)
- **Problem Statement:** Multi-system refund and payout pipelines risk double-paying customers after mid-batch crashes, treating a gateway `200 OK` as settled money, or breaking when a payment provider changes webhook fields.
- **What the Solution Looks Like:**
  - **What we actually build & run:** A **FastAPI + HTMX/SSE Settlement Runner**, a **Pydantic AI batch worker**, and **3 local mock services** (Payment Gateway, Order Store, Double-Entry Ledger) wired to MongoDB Atlas.
  - **What it looks like in the browser:**
    ```text
    +-------------------------------------------------------------------------+
    | Batch: "Daily Refund Run (5 Claims)"   [ Crash Worker ]  [ Mutate API ] |
    +-------------------------------------------------------------------------+
    | Claim #1 ($45)   Gateway: SETTLED    Ledger: POSTED (1x)   [VERIFIED]   |
    | Claim #2 ($120)  Gateway: SETTLED    Ledger: POSTED (1x)   [VERIFIED]   |
    | Claim #3 ($80)   Gateway: 202 SENT   Probe: UNSETTLED -> Retrying...    |
    | Claim #4 ($2500) Policy Gate >$500   [ElevenLabs Voice PIN Required]    |
    | Claim #5 ($60)   Pending (waiting resume after simulated worker crash)  |
    +-------------------------------------------------------------------------+
    ```
  - **End-to-end flow:** You start a 5-claim batch. Claims #1–2 settle and write balanced double-entry records. You crash the worker mid-batch and restart it—Claims #1–2 are skipped via idempotency keys (zero double refunds). Claim #4 ($2,500) exceeds the $500 policy cap, prompting an ElevenLabs voice PIN before calling the gateway (or reversing prior legs if aborted).
- **Concrete Use Case & What You See:**
  - *Scenario:* Process a batch of 5 customer refund/chargeback claims across 3 local mock services: Payment Gateway, Order System, and Double-Entry Ledger.
- **MongoDB Data Stored:**
  - `settlement_claims` & `ledger_entries`: Idempotency keys, debit/credit legs, `gateway_tx_id`, `settlement_verified: bool`.
  - `policy_gates`: Per-operator refund limits, voice approval transcripts, compensating reversal records.
  - `gateway_drift_fixes` (Vector Search): Past webhook schema mappings and gateway error resolutions.
- **Tradeoff:** High universal **Impact (20%)** and easy for any judge to grasp, *if* we scope the mock gateway/ledger convincingly without wasting hours fabricating transaction history or sounding like standard fintech automation.

### Option 6: Closed-Loop Incident Mitigation & Verification Executor

- **Primary Track:** Track 3 (*Finish the Job*) + Track 1 (*Agents You Can Audit*)
- **Problem Statement:** Automated incident responders often execute a restart or config fix, see exit code `0`, and close the alert—even though the service is still unhealthy or a half-applied fix left infrastructure worse off.
- **What the Solution Looks Like:**
  - **What we actually build & run:** A **FastAPI + HTMX/SSE Incident Runner**, a **Pydantic AI SRE agent**, and a **real local Dockerized web app + reverse proxy** (using our local Docker setup) that we intentionally break on stage.
  - **What it looks like in the browser:**
    ```text
    +-------------------------------------------------------------------------+
    | Target App Health: 502 BAD GATEWAY  [ Break Proxy ]  [ Voice Approve ]  |
    +------------------------------------+------------------------------------+
    | MITIGATION EXECUTION               | LIVE PROBE & ROLLBACK STATE        |
    | 1. Diagnose nginx/proxy upstream   | Probe GET /health -> 502           |
    | 2. Proposed fix: patch upstream    | Snapshot saved: proxy_conf_v3      |
    |    -> Gate: VOICE SUDO REQUIRED    |                                    |
    | 3. Apply fix + reload container    | Probe GET /health -> 200 OK!       |
    |    (If still 502 -> auto-rollback) | Status: VERIFIED RECOVERED         |
    +------------------------------------+------------------------------------+
    ```
  - **End-to-end flow:** You click **Break Proxy** so the real local container starts returning `502`. The agent inspects logs/config, queries Vector Search for past fixes, asks for spoken ElevenLabs confirmation before modifying config, applies the fix, and only marks the incident resolved after an independent HTTP `/health` probe returns `200 OK` consistently—auto-rolling back if the probe fails.
- **Concrete Use Case & What You See:**
  - *Scenario:* A local Dockerized web app + reverse proxy starts returning `502 Bad Gateway` (simulated bad route or crashed worker container). The agent diagnoses it, proposes a mitigation plan, restarts/patches the target, and runs an **independent HTTP health + latency probe** before marking it fixed.
- **MongoDB Data Stored:**
  - `incidents` & `mitigation_steps`: Observed health-probe metrics before/after, commands attempted, `exit_zero_only` vs `health_verified` status, rollback snapshots.
  - `runbook_memories` (**Atlas Vector Search**): Past incident signatures and fixes, scoped by environment (`staging` vs `prod`) with expiry/correction when a fix stops working.
  - `safety_policies`: Blocked destructive commands and authority approvals.
- **Tradeoff:** Maximum engineering authenticity and great live chaos demo, though slightly narrower audience than Option 1 or Option 2's broader framing.

### Option 7: Multi-Portal Partner / Compliance Provisioning Autopilot

- **Primary Track:** Track 3 (*Finish the Job*) + Track 1 (*Agents You Can Audit*)
- **Problem Statement:** Onboarding a B2B partner across disconnected portals (SSO, Billing, Webhooks, Storage) constantly stalls on async propagation delays, half-created orphaned accounts when a step fails, or sudden vendor form/API changes.
- **What the Solution Looks Like:**
  - **What we actually build & run:** A **FastAPI + HTMX/SSE Onboarding Console**, a **Pydantic AI provisioning agent**, and **4 lightweight local FastAPI vendor mocks** (SSO, Billing, Webhooks, Storage) wired to MongoDB Atlas.
  - **What it looks like in the browser:**
    ```text
    +-------------------------------------------------------------------------+
    | Partner: "Northstar Logistics"   [ Start Onboarding ]  [ Abort & Undo ] |
    +-------------------------------------------------------------------------+
    | 1. SSO Portal:      202 Accepted -> Polling until user active -> DONE   |
    | 2. Storage Bucket:  Created s3://northstar-drop (undo ID saved) -> DONE |
    | 3. Billing Portal:  422 Missing new field "tax_region"                  |
    |    -> ElevenLabs asks ops lead by voice -> Captured "ON-CA" -> DONE    |
    | 4. Webhook Setup:   Verified test ping 200 OK -> ONBOARDING COMPLETE    |
    +-------------------------------------------------------------------------+
    ```
  - **End-to-end flow:** You launch onboarding for `"Northstar Logistics"`. Step 1 catches SSO's async delay (`202` before the user is queryable). Step 2 saves the created bucket ID for rollback. Step 3 hits a newly added vendor field (`tax_region`); ElevenLabs asks you by voice, records `"ON-CA"`, and completes Billing. If you click **Abort & Undo** mid-run, it deletes the created bucket and SSO tenant so zero orphaned resources remain.
- **Concrete Use Case & What You See:**
  - *Scenario:* Onboard a new partner (`"Northstar Logistics"`) across 4 mock vendor APIs: Identity/SSO, Billing Plan, Webhook Subscription, and S3 Bucket Policy.
- **MongoDB Data Stored:**
  - `onboarding_jobs` & `vendor_steps`: Partner profile, per-vendor created resource IDs (needed for teardown!), propagation probe states, compensating delete payloads.
  - `vendor_field_mappings` (Vector Search): Learned schema mappings across vendor API versions.
  - `compliance_gates`: Pre-provisioning checks and human voice-capture transcripts.
- **Tradeoff:** Clean B2B story and intuitive rollback, though requires building 4 believable mock vendor endpoints cleanly.

---

## Quick Comparison Matrix

| Option | Primary Track | Data Realism in 1 Day | Novelty / Creativity | Main Risk to Watch |
| :--- | :--- | :--- | :--- | :--- |
| **1. Agent `sudo` + `Ctrl+Z` Proxy** | Track 1 (Audit) | Real GitHub / Docker / DB targets | Very high (infrastructure primitive) | Keep target tools to 3 concrete mutations so rollback is 100% real |
| **2. Chaos-Tested Cutover Closer** | Track 3 (Finish) | Real OpenAPI `v1 -> v2` + live HTTP services | High (live `SIGKILL` + API drift on stage) | Frame business impact clearly for non-SRE judges |
| **3. Causal Memory Firewall** | Track 2 (Memory) | Real GitHub org policies or Toronto Open Data | High *if* counterfactual diff + LangSmith proof shine | Must stay clearly distinct from "RAG + tenant filter" |
| **4. Live Civic / Transit Closer** | Track 3 (Finish) | Live public weather / transit feeds | Medium-high (vivid real-world story + voice) | Avoid spending hours wrangling messy external feed parsers |
| **5. Financial Settlement Closer** | Track 3 / Track 1 | Simulated gateway + double-entry ledger | Medium (familiar domain, strong rigor) | Synthetic financial data can feel contrived |
| **6. Incident Mitigation Closer** | Track 3 / Track 1 | Real local Docker containers / proxy configs | Medium-high (authentic SRE demo) | Avoid looking like a monitoring dashboard |
| **7. Partner Provisioning Autopilot** | Track 3 / Track 1 | 4 local mock vendor APIs | Medium (familiar B2B onboarding flow) | Building 4 realistic mock vendors eats time |

---

## Questions to Align On Before Locking `mh-f6q`

1. **Which pitch feels strongest to tell in 3 minutes?** (Infrastructure primitive like **Option 1**, live chaos resilience like **Option 2**, counterfactual memory governance like **Option 3**, or a real-world operations story like **Option 4 / 5**?)
2. **Which official track gives us the clearest win?** (Locking one primary track for `mh-f6q` while keeping 1–2 crisp mechanics from the others.)
3. **What is the single best 30-second "wow" moment for the ElevenLabs voice hook?** (Voice `sudo` approval, spoken drift escalation, or voice memory correction/TTL?)
