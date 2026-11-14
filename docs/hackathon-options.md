# Agents in Context Toronto — Project Options & Track Alignment

A decision brief comparing candidate project directions for our 2-person, 1-day sprint (~6h15m: 10:45 AM – 5:00 PM ET).

## Hackathon Constraints & Judging Criteria

- **Mandatory Infrastructure:** MongoDB Atlas Sandbox (`Cluster0`, Dedicated M10, MongoDB 9.0.7 — supports Search, Vector Search, Change Streams, JSON Schema validation). Public GitHub repo, New Work Only, 1-minute submission video + 3-minute live demo.
- **Strictly Prohibited (Instant DQ):** Streamlit apps, basic RAG apps, dashboard-as-main-feature, AI job application screeners, image analyzers, mental health/medical/nutrition/education/personality/sports analyzers.
- **Round 1 Judging:** **35%** Technical Demo · **30%** Implementation Difficulty · **20%** Impact · **15%** Creativity *(Round 2 top 6: 25% each)*.
- **Prizes & Side Tracks:** Overall 1st/2nd/3rd (MongoDB + LangSmith + ElevenLabs) + **Best Project Built with ElevenLabs** side track.
- **Planned Core Stack:** Python 3.14, FastAPI + minimal HTMX/SSE live operator theater (no heavy SPA/CSS time sink), MongoDB Atlas, Pydantic AI + Logfire, LangSmith tracing/evals, and a targeted ElevenLabs voice hook.

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
- **Concrete Use Case & What You See:**
  - *Scenario:* An engineer asks the agent to *"prepare a staging hotfix release"* across 3 real targets: (1) create a GitHub branch & release note commit in a test repo, (2) raise a rate-limit setting in a local FastAPI config service, and (3) attempt to purge a `prod` cache / force-push `main`.
  - *On Screen (HTMX + SSE):* Left column shows the live step-by-step **Plan & Authority Chain** (`human:hussain -> role:staging_ops -> agent:release_bot`); right column shows live **Target State** (the actual GitHub branch, config version `v14 -> v15`, and container state). Step 2 pauses at a yellow `AWAITING VOICE SUDO` gate (ElevenLabs speaks the risk summary and accepts your spoken `"approve staging only"`); Step 3 hits a red `BLOCKED PRE-ACTION` policy gate before touching `prod`. Clicking **"Rewind to Step 0"** executes the inverse actions and snaps the real GitHub branch and service config back to `v14`.
- **MongoDB Data Stored:**
  - `delegations`: Human principal, role, allowed resource scopes, max auto-approved risk tier, expiry.
  - `policies`: Declarative allow / `require_voice_sudo` / deny rules enforced with MongoDB JSON Schema validation.
  - `action_intents`: One doc per tool call with `authority_chain`, `rationale`, `tool` + polymorphic `args`, `gate_decision` (+ voice transcript), `pre_state` snapshot, registered `compensating_action`, `post_state`, and `rollback.status`.
  - `runs` (watched via **Atlas Change Streams**): Live `halt_requested` and `rewind_to_step` triggers that interrupt the worker before the next step.
- **The Pitch:** Teams don't block agents because models aren't smart enough—they block them because agents have no `sudo` and no `Ctrl+Z`. Instead of building "an agent for X," this builds the auditable execution runtime wrapping any Pydantic AI agent.
- **Believable Targets (Zero Fake Data):** Drives real actions against resources we control directly: a test GitHub repository (issues/branches/PRs), local Docker containers/files, and a local DB or S3-compatible store.
- **ElevenLabs Hook:** Spoken `"sudo"` approval channel—when an agent hits a high-risk action gate, it calls out for voice confirmation before proceeding.
- **3-Minute Demo Flow:** Kick off the staging release task -> watch an unauthorized `prod` step get blocked pre-execution -> approve a gated config step by voice -> trigger mid-run halt & rewind, proving real resources revert cleanly -> inspect causal trace in Logfire/LangSmith.
- **Partner / GTM Role:** Frame the enterprise trust gap, design the risky edge-case prompts for the LangSmith eval suite, and operate the live kill/rewind controls on stage.

---

### Option 2: "The Unkillable Integrator" — Chaos-Tested API Cutover & Schema-Drift Closer

- **Primary Track:** Track 3 (*Finish the Job*) · *Crosses into Track 1 (gates/rollback) & Track 2 (fix memory)*
- **Problem Statement:** Multi-step API workflows silently break in the real world: webhooks return `202 Accepted` without actually processing, workers crash mid-run causing duplicate side effects, and downstream APIs rename fields overnight.
- **Concrete Use Case & What You See:**
  - *Scenario:* We run a 4-step *"New Customer Workspace Cutover"* across 3 real local FastAPI microservices (Auth Service, Webhook Dispatcher, Billing/Quota Service): create tenant -> register webhook -> enable quota -> verify live webhook delivery.
  - *On Screen (HTMX + SSE):* Top bar has 3 big red **Chaos Buttons**: `1. Drop Async Webhook`, `2. SIGKILL Worker`, `3. Deploy Breaking API v2`. As the agent runs, each step moves from `pending -> sent -> verified_took_effect`. When you click `Drop Async Webhook`, the agent's independent probe catches that the webhook returned `202` but never registered (`only-sent`), and retries idempotently. When you `SIGKILL` the Python worker and restart it, it picks up cleanly at Step 3 without recreating the tenant. When you deploy `API v2` (renaming `webhook_url` -> `callback_uri` and `secret` -> `hmac_key`), the agent searches past OpenAPI drift fixes in Atlas Vector Search, adapts its payload, and finishes—or escalates via ElevenLabs voice if a new required field has no safe default.
- **MongoDB Data Stored:**
  - `workflow_runs` & `step_checkpoints`: Idempotency keys, `status` (`pending | sent | verified_took_effect | failed`), retry counts, external resource IDs, and probe results.
  - `api_drift_playbooks` (**Atlas Vector Search**): Past OpenAPI diffs, field-mapping rules, error signatures, and confidence scores (invalidatable if a fix turns out wrong).
  - `service_events`: Live HTTP request/response traces and verification probe evidence.
- **Believable Data / Targets:** 2–3 lightweight FastAPI/Docker mock external services with real OpenAPI `v1` and `v2` specs (renamed fields, changed auth/status codes, and a `202 Accepted` endpoint that silently drops async work). The OpenAPI specs, HTTP traces, and Atlas checkpoints *are* the data.
- **ElevenLabs Hook:** Voice escalation when the agent encounters an ambiguous breaking schema change with low confidence, asking the operator how to map the new field.
- **Partner / GTM Role:** Anchor the business pain of silent webhook/integration failures, narrate the chaos sequence, and trigger the live chaos buttons during the demo.
- **Watch-out:** Frame the story in crisp business terms so non-SRE judges feel the impact immediately.

---

### Option 3: Causal Memory Firewall — Multi-Tenant Ops Triage with Provable Memory Diffs

- **Primary Track:** Track 2 (*Memory You Can Govern*) · *Crosses into Track 1 (authority-scoped writes)*
- **Problem Statement:** AI agents with long-term memory silently leak policies across teams/clients and keep obeying stale or wrong facts even after humans correct them—and most demos can't prove memory actually changed a decision.
- **Concrete Use Case & What You See:**
  - *Scenario:* An operations triage agent routes incoming support/issue tickets for two isolated orgs sharing one platform (e.g., **Org A: `vercel/next.js` vs Org B: `fastapi/fastapi`**, or **Ward A vs Ward B municipal rules**). Both orgs have overlapping terms ("security report", "breaking regression", "escalate to maintainer"), but opposite routing rules.
  - *On Screen (HTMX + SSE):* A **Split-Screen Counterfactual Runner**. You feed the *exact same ticket* into Tenant A and Tenant B: Tenant B misroutes it because of an outdated remembered rule (`"Route all auth tickets to legacy-team"`). You click or speak into ElevenLabs: *"Expire the legacy-team rule for Tenant B; route auth tickets to security-triage."* Immediately, the UI re-runs the same ticket: Tenant B's decision flips cleanly, Tenant A is untouched, and a **LangSmith Eval Badge** shows `Cross-Tenant Leak: 0% | Post-Correction Flip: 100%`.
- **MongoDB Data Stored:**
  - `tenant_memories` (**Atlas Vector Search**): Memory text + embedding, strict `tenant_id` / `role_acl` filter fields, `source_authority`, `created_at`, `expires_at` (TTL), and `superseded_by` / `status` (`active | invalidated | expired`).
  - `memory_audit_log`: Who wrote, read, corrected, or expired each memory and which `run_id` consumed it.
  - `counterfactual_runs`: Before-and-after decision snapshots (`memory_snapshot_v1 -> decision_A` vs `memory_snapshot_v2 -> decision_B`) proving causal impact.
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
- **Concrete Use Case & What You See:**
  - *Scenario:* A live Environment Canada weather alert or Toronto TTC service disruption triggers a multi-step response: (1) classify affected zones/routes, (2) update active detour status in a local dispatch board, (3) notify 3 downstream webhook channels (ops Slack mock, rider SMS mock, partner carrier API), and (4) verify every channel actually acknowledged receipt.
  - *On Screen (HTMX + SSE):* Live feed card on the left showing the real fetched weather/transit alert; step-by-step **Dispatch Execution & Verification** on the right. Channel #2 simulates an unacknowledged drop (`only-sent`), so the agent reroutes via fallback channel; when the disruption scope crosses a broadcast threshold (e.g., >5 zones), a Track 1 policy gate triggers **ElevenLabs** to read a 10-second spoken incident brief and ask the dispatcher for verbal confirmation before broadcasting city-wide.
- **MongoDB Data Stored:**
  - `disruption_events`: Raw real feed snapshots (Environment Canada / TTC JSON), normalized severity, affected corridors.
  - `dispatch_runs` & `delivery_checkpoints`: Per-channel `sent` vs `verified_acked` state, retry/fallback history, crash-resume cursor.
  - `dispatch_policies`: Max auto-broadcast radius, quiet-hours / approval thresholds, operator approval records.
- **Believable Data / Targets:** Live Environment Canada / OpenWeather alerts and Toronto Open Data / TTC feeds driving a local dispatch and webhook/notification target.
- **Partner / GTM Role:** Own the civic/operations narrative and live voice interaction on stage.
- **Watch-out:** Keep feed parsing minimal (1–2 clean JSON endpoints) so GTFS/feed quirks don't consume the 6-hour build budget.

---

## Earlier Domain Variations (Still on the Table if Data Is Scoped Tightly)

These three earlier variations share the same Track 3 + Track 1/2 engine and can be paired with realistic local mocks if a narrower operational story appeals more:

### Option 5: Idempotent Financial / Order Settlement Closer

- **Primary Track:** Track 3 (*Finish the Job*) + Track 1 (*Agents You Can Audit*)
- **Problem Statement:** Multi-system refund and payout pipelines risk double-paying customers after mid-batch crashes, treating a gateway `200 OK` as settled money, or breaking when a payment provider changes webhook fields.
- **Concrete Use Case & What You See:**
  - *Scenario:* Process a batch of 5 customer refund/chargeback claims across 3 local mock services: Payment Gateway, Order System, and Double-Entry Ledger.
  - *On Screen (HTMX + SSE):* Live batch table showing each claim moving `initiated -> gateway_sent -> ledger_verified`. Clicking **"Crash Worker"** mid-batch stops execution at claim #3 and restarts cleanly without double-refunding claims #1–2; clicking **"Gate High-Value Refund ($2,500)"** pauses claim #4 for an ElevenLabs voice PIN/approval or reverses the prior journal entry on abort; mutating the mock gateway's webhook payload triggers Vector Search adaptation.
- **MongoDB Data Stored:**
  - `settlement_claims` & `ledger_entries`: Idempotency keys, debit/credit legs, `gateway_tx_id`, `settlement_verified: bool`.
  - `policy_gates`: Per-operator refund limits, voice approval transcripts, compensating reversal records.
  - `gateway_drift_fixes` (Vector Search): Past webhook schema mappings and gateway error resolutions.
- **Tradeoff:** High universal **Impact (20%)** and easy for any judge to grasp, *if* we scope the mock gateway/ledger convincingly without wasting hours fabricating transaction history or sounding like standard fintech automation.

### Option 6: Closed-Loop Incident Mitigation & Verification Executor

- **Primary Track:** Track 3 (*Finish the Job*) + Track 1 (*Agents You Can Audit*)
- **Problem Statement:** Automated incident responders often execute a restart or config fix, see exit code `0`, and close the alert—even though the service is still unhealthy or a half-applied fix left infrastructure worse off.
- **Concrete Use Case & What You See:**
  - *Scenario:* A local Dockerized web app + reverse proxy starts returning `502 Bad Gateway` (simulated bad route or crashed worker container). The agent diagnoses it, proposes a mitigation plan, restarts/patches the target, and runs an **independent HTTP health + latency probe** before marking it fixed.
  - *On Screen (HTMX + SSE):* Live target health indicator (`502 -> 200 OK`), mitigation step ledger, and chaos toggles (*"Break Proxy Config"*, *"Block Dangerous `rm`/Volume Action"*). High-risk actions pause for spoken **ElevenLabs** on-call approval (`"Approve container restart"`), and if the health probe still fails after mitigation, it rolls back the config change automatically.
- **MongoDB Data Stored:**
  - `incidents` & `mitigation_steps`: Observed health-probe metrics before/after, commands attempted, `exit_zero_only` vs `health_verified` status, rollback snapshots.
  - `runbook_memories` (**Atlas Vector Search**): Past incident signatures and fixes, scoped by environment (`staging` vs `prod`) with expiry/correction when a fix stops working.
  - `safety_policies`: Blocked destructive commands and authority approvals.
- **Tradeoff:** Maximum engineering authenticity and great live chaos demo, though slightly narrower audience than Option 1 or Option 2's broader framing.

### Option 7: Multi-Portal Partner / Compliance Provisioning Autopilot

- **Primary Track:** Track 3 (*Finish the Job*) + Track 1 (*Agents You Can Audit*)
- **Problem Statement:** Onboarding a B2B partner across disconnected portals (SSO, Billing, Webhooks, Storage) constantly stalls on async propagation delays, half-created orphaned accounts when a step fails, or sudden vendor form/API changes.
- **Concrete Use Case & What You See:**
  - *Scenario:* Onboard a new partner (`"Northstar Logistics"`) across 4 mock vendor APIs: Identity/SSO, Billing Plan, Webhook Subscription, and S3 Bucket Policy.
  - *On Screen (HTMX + SSE):* A 4-step provisioning checklist with live status probes (catching when SSO returns `202` before the user actually exists). If Step 3 fails compliance or you hit **"Abort Onboarding,"** the agent runs compensating `DELETE` calls to tear down Steps 1–2 cleanly. If the Billing mock adds a brand-new required field (`tax_region`), **ElevenLabs** asks the ops lead by voice for the value, captures the answer, and finishes provisioning.
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
