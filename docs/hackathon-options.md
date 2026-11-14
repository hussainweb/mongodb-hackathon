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
- **The Pitch:** Teams don't block agents because models aren't smart enough—they block them because agents have no `sudo` and no `Ctrl+Z`. Instead of building "an agent for X," this builds the auditable execution runtime wrapping any Pydantic AI agent.
- **Believable Targets (Zero Fake Data):** Drives real actions against resources we control directly: a test GitHub repository (issues/branches/PRs), local Docker containers/files, and a local DB or S3-compatible store.
- **Core Mechanics:**
  - Every tool call carries an explicit authority chain (`human -> role -> agent -> tool`).
  - MongoDB JSON Schema + pre-action policy gates block unauthorized mutations *before* execution.
  - Before executing an approved step, the proxy captures a pre-state snapshot and registers a compensating inverse action in Atlas.
  - Atlas Change Streams power a live kill-switch and time-travel rewind (`"Stop & roll back to step 2"`).
- **ElevenLabs Hook:** Spoken `"sudo"` approval channel—when an agent hits a high-risk action gate, it calls out for voice confirmation before proceeding.
- **3-Minute Demo Flow:** Kick off a multi-step engineering/ops task -> watch an over-privileged step get blocked pre-execution -> approve a gated step by voice -> trigger mid-run halt & rewind, proving real resources revert cleanly -> inspect causal trace in Logfire/LangSmith.
- **Partner / GTM Role:** Frame the enterprise trust gap, design the risky edge-case prompts for the LangSmith eval suite, and operate the live kill/rewind controls on stage.

---

### Option 2: "The Unkillable Integrator" — Chaos-Tested API Cutover & Schema-Drift Closer

- **Primary Track:** Track 3 (*Finish the Job*) · *Crosses into Track 1 (gates/rollback) & Track 2 (fix memory)*
- **The Pitch:** Most hackathon agents only survive happy-path demos. Here, **live failure injection is the showcase**: a Pydantic AI workflow orchestrator must finish a multi-service cutover/provisioning job while we actively lie to it, kill its worker process, and break downstream API contracts mid-flight.
- **Believable Data / Targets:** 2–3 lightweight FastAPI/Docker mock external services with real OpenAPI `v1` and `v2` specs (renamed fields, changed auth/status codes, and a `202 Accepted` endpoint that silently drops async work). The OpenAPI specs, HTTP traces, and Atlas checkpoints *are* the data.
- **Core Mechanics:**
  - Atlas checkpoint state machine (`pending -> sent -> verified_took_effect`) paired with independent verification probes.
  - Surviving a live `SIGKILL` mid-run and resuming from the last verified checkpoint without duplicating prior mutations.
  - **Atlas Vector Search** over past OpenAPI diffs and drift-resolution playbooks to adapt when a downstream service switches from `v1` to `v2` mid-run.
  - Pre-action destructive-change policy gate + compensating teardown (Track 1) and invalidatable fix memory (Track 2).
- **ElevenLabs Hook:** Voice escalation when the agent encounters an ambiguous breaking schema change with low confidence, asking the operator how to map the new field.
- **3-Minute Demo Flow:** Start a 4-service provisioning run -> trigger *"Silent Drop"* (verification probe catches `only-sent` vs `took-effect`) -> hit *"Kill Worker (`SIGKILL`)"* and restart (resumes seamlessly) -> click *"Deploy Breaking API v2"* mid-run (agent recalls past drift pattern via Vector Search and finishes).
- **Partner / GTM Role:** Anchor the business pain of silent webhook/integration failures, narrate the chaos sequence, and trigger the live chaos buttons during the demo.
- **Watch-out:** Frame the story in crisp business terms so non-SRE judges feel the impact immediately.

---

### Option 3: Causal Memory Firewall — Multi-Tenant Ops Triage with Provable Memory Diffs

- **Primary Track:** Track 2 (*Memory You Can Govern*) · *Crosses into Track 1 (authority-scoped writes)*
- **The Pitch:** Track 2 explicitly demands proving that memory *changed behavior* rather than merely stuffing a prompt. This system puts **counterfactual replay** front and center: run a workflow for Tenant A vs. Tenant B, edit or expire a memory mid-demo, and prove deterministically that the decision flipped with zero cross-tenant leakage.
- **Believable Data / Targets (Real Public Corpora):**
  - *Path A:* Real public GitHub issues/PRs and maintainer policies across 2–3 open-source repositories (each org = an isolated tenant ACL).
  - *Path B:* Real Toronto Open Data (municipal bylaws, 311 routing rules, or ward/department policies).
- **Core Mechanics:**
  - Single Atlas Vector Search index with strict per-tenant/per-role ACL filtering.
  - Explicit memory lifecycle metadata (TTL, source authority, superseded/invalidated status).
  - Counterfactual side-by-side runner + **LangSmith** evals measuring leak rate (`0%`) and post-correction decision flip rate (`100%`).
- **ElevenLabs Hook:** Voice-driven governance—speak *"Deprecate rule X for Org B as of today"* to invalidate/TTL a memory live and immediately watch the re-run change outcome.
- **3-Minute Demo Flow:** Triage the same scenario under Tenant A and Tenant B -> show Tenant B's stale/wrong remembered policy causing an error -> issue a spoken correction/TTL -> re-run the exact input and show Logfire/LangSmith proving the behavioral diff and zero cross-tenant bleed.
- **Partner / GTM Role:** Curate real policy conflicts across tenants and build the adversarial counterfactual test cases for LangSmith.
- **Watch-out:** Must remain unmistakably distinct from "RAG + metadata filter."

---

### Option 4: Live-Feed Disruption Closer (Civic / Transit / Weather Dispatch)

- **Primary Track:** Track 3 (*Finish the Job*) · *Crosses into Track 1 (dispatch caps) & ElevenLabs*
- **The Pitch:** Step outside developer tools into a high-visibility operational domain powered by live public feeds rather than static fixtures. When a real weather or transit disruption hits, the agent coordinates multi-step rerouting and stakeholder notifications, verifies downstream delivery, and escalates policy exceptions by voice.
- **Believable Data / Targets:** Live Environment Canada / OpenWeather alerts and Toronto Open Data / TTC feeds driving a local dispatch and webhook/notification target.
- **Core Mechanics:**
  - Atlas-backed dispatch state machine verifying downstream acknowledgments (`only-sent` vs `took-effect`).
  - Crash-resumable execution across multi-channel notifications.
  - Pre-action policy bounds (e.g., max reroute cost or broadcast scope) before sending public alerts.
- **ElevenLabs Hook:** Real-time spoken incident briefing for the human dispatcher + verbal approval to override a dispatch cap.
- **Partner / GTM Role:** Own the civic/operations narrative and live voice interaction on stage.
- **Watch-out:** Keep feed parsing minimal (1–2 clean JSON endpoints) so GTFS/feed quirks don't consume the 6-hour build budget.

---

## Earlier Domain Variations (Still on the Table if Data Is Scoped Tightly)

These three earlier variations share the same Track 3 + Track 1/2 engine and can be paired with realistic local mocks if a narrower operational story appeals more:

### Option 5: Idempotent Financial / Order Settlement Closer

- **Primary Track:** Track 3 (*Finish the Job*) + Track 1 (*Agents You Can Audit*)
- **Idea:** Double-entry/idempotent refund, payout, or chargeback closer across Payment Gateway -> Order System -> Ledger. Prevents double-refunds after mid-batch crashes, detects `200 OK` vs. actual settlement, adapts to gateway webhook schema drift via Vector Search, and enforces spend-cap policy gates with compensating ledger reversals.
- **Tradeoff:** High universal **Impact (20%)** and easy for any judge to grasp, *if* we scope the mock gateway/ledger convincingly without wasting hours fabricating transaction history or sounding like standard fintech automation.

### Option 6: Closed-Loop Incident Mitigation & Verification Executor

- **Primary Track:** Track 3 (*Finish the Job*) + Track 1 (*Agents You Can Audit*)
- **Idea:** An autonomous remediation executor (targeting real local Docker containers / mock proxy rules) that never trusts exit code `0`—it runs independent health/effect probes, survives crashes, adapts to config/API drift via Vector Search over past postmortems, gates destructive commands, and takes hands-free ElevenLabs voice approvals.
- **Tradeoff:** Maximum engineering authenticity and great live chaos demo, though slightly narrower audience than Option 1 or Option 2's broader framing.

### Option 7: Multi-Portal Partner / Compliance Provisioning Autopilot

- **Primary Track:** Track 3 (*Finish the Job*) + Track 1 (*Agents You Can Audit*)
- **Idea:** Onboards a new partner/tenant across 4 mock external systems (SSO, Billing, Webhooks, Storage) with verified endpoint checks, full compensating teardown on mid-run abort, Vector Search field-mapping recovery on vendor API changes, and ElevenLabs voice capture when an unknown required field appears.
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
