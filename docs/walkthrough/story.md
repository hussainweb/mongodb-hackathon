---
title: FinishLine
subtitle: Multi-page, chaos-resumable GitHub and deployment release closer
repo: /home/hw/work/mongodb-hackathon
remote: https://github.com/hussainweb/mongodb-hackathon
commit: 8c51030
editor: vscode
---

# What it is

FinishLine ("Track 3: Finish the Job") accepts either an open GitHub issue or a free-form release goal (`issue_number=0`), recalls repository-scoped rules and drift playbooks from MongoDB Atlas Vector Search, opens a patch branch and pull request, deploys to a downstream microservice, verifies real activation via `GET /verify/{deployment_id}` rather than trusting `202 Accepted`, survives `SIGKILL` crashes via ACID Atlas checkpoints, and pauses between checkpoints when stepped manually.

## Purpose and running scope
scene: context
reveal: finishline
camera: all
caption: A local two-service Python 3.14 system with three standalone UI pages and Atlas persistence
evidence: README.md:1-5, pyproject.toml:9, src/mongodb_hackathon/__init__.py:13-66, src/mongodb_hackathon/config.py:18-55, src/mongodb_hackathon/app.py:306, src/mongodb_hackathon/app.py:358-515, src/mongodb_hackathon/target_service.py:14, src/mongodb_hackathon/target_service.py:52-70, src/mongodb_hackathon/agent.py:10, src/mongodb_hackathon/agent.py:24-33, src/mongodb_hackathon/embeddings.py:35-46, src/mongodb_hackathon/static/live-run.js:187-213, src/mongodb_hackathon/mongo.py:343-388, src/mongodb_hackathon/github_adapter.py:43-44, docs/hackathon-options.md:14, docs/hackathon-options.md:62, docs/hackathon-options.md:85

What runs today is a local two-service Python 3.14 FastAPI system (`:8000` Control Room serving standalone `/`, `/infra`, and `/store` pages plus `:8001` in-memory Target Service) backed by remote MongoDB Atlas, OpenAI, optional LangSmith/Logfire/ElevenLabs, and curated live or `dry-run/` GitHub repositories. Instead of three separate microservices, Voyage AI embeddings, HTMX fragments, or RBAC `delegations` described in `docs/hackathon-options.md`, the codebase uses one in-memory target service, OpenAI `text-embedding-3-small`, vanilla JS over `EventSource` SSE, and `source_repo`-scoped `experience_memories`.

## The people
reveal: operator, developer, principal, operator->finishline, developer->finishline, principal->finishline
highlight: operator, developer, principal
camera: operator, developer, principal, finishline
caption: Two implemented human roles and one design-only policy role
evidence: src/mongodb_hackathon/app.py:358-1178, src/mongodb_hackathon/templates/index.html:19-203, src/mongodb_hackathon/templates/infra.html:18-262, src/mongodb_hackathon/templates/store.html:31-426, mise.toml:1-40, docs/hackathon-options.md:62

Two human roles exist in code today. The **Operator** uses the unauthenticated Control Room pages to choose or register a repository in `demo_repos`, enter a free-form release prompt or issue chip, select a pacing preset or `Step-by-Step` mode, inspect or re-plan Step 1 `FixPlan`, advance paused runs, trigger `SIGKILL`/resume/rollback, inject faults on `/infra`, and govern `experience_memories` on `/store`. The **Developer / Evaluator** runs `mise run seed`, `mise run check`, `mise run evals`, and `mise run walkthrough`. A third role from the design docs—a **Scoped Human Principal** bound to `delegations` RBAC scopes—does not exist anywhere in code.

## External systems in code
reveal: atlas, github, openai, elevenlabs, telemetry, finishline->atlas, finishline->github, finishline->openai, finishline->elevenlabs, finishline->telemetry
highlight: atlas, github, openai, elevenlabs, telemetry
camera: finishline, atlas, github, openai, elevenlabs, telemetry
caption: Six runtime integrations plus local gh CLI and MCP developer tooling
evidence: src/mongodb_hackathon/mongo.py:26-213, src/mongodb_hackathon/mongo.py:232-435, src/mongodb_hackathon/models.py:139, src/mongodb_hackathon/config.py:22-41, src/mongodb_hackathon/github_adapter.py:13-25, src/mongodb_hackathon/github_adapter.py:55-432, src/mongodb_hackathon/seed.py:130-176, src/mongodb_hackathon/agent.py:10-231, src/mongodb_hackathon/embeddings.py:20-46, src/mongodb_hackathon/voice.py:15-62, src/mongodb_hackathon/worker.py:175-177, .agents/mcp_config.json:1-25

At runtime, FinishLine talks to **MongoDB Atlas** (ACID checkpoint transactions, `$jsonSchema` validation, 7-day TTL events, `source_repo`-filtered `$vectorSearch`, and Change Streams), **GitHub REST API** (reading `pydantic/pydantic-ai` and `fastapi/fastapi` issues during seeding, provisioning sandboxes, branching, committing, opening PRs, commenting, and labeling), and **OpenAI** (`gpt-4.1-mini` and `text-embedding-3-small`, each with deterministic fallbacks). When configured, it calls **ElevenLabs** (`eleven_flash_v2_5` TTS and `scribe_v2` STT), **LangSmith** (`trace()` spans), and **Logfire**, falling back to `gh auth token` when `GITHUB_TOKEN` is unset. `.agents/mcp_config.json` configures MongoDB and Serena MCP servers for developer tooling only.

## External systems in design only
reveal: voyage, htmx, finishline->voyage, finishline->htmx
highlight: voyage, htmx
camera: all
caption: Voyage AI, HTMX, and multi-service targets remain design placeholders
evidence: docs/hackathon-options.md:14, docs/hackathon-options.md:71, docs/hackathon-options.md:85, docs/hackathon-options.md:178, .env.example:21-23, pyproject.toml:10-24, src/mongodb_hackathon/config.py:23-24, src/mongodb_hackathon/embeddings.py:35-46, src/mongodb_hackathon/templates/base.html:1-110, src/mongodb_hackathon/static/live-run.js:187-213

Several technologies mentioned in `.env.example` and `docs/hackathon-options.md` are absent from runtime code. `VOYAGE_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY` appear only as `.env.example` placeholders, while `embeddings.py` calls OpenAI `text-embedding-3-small`. Likewise, `HTMX`, Environment Canada / TTC feeds, and separate Auth/Webhook/Billing target services exist only in planning notes; templates extend `base.html` with vanilla JS and `EventSource`.

# The pieces

FinishLine splits its runtime across a lightweight launcher (`mise run server` / `mongodb-hackathon`), two FastAPI apps, detached worker OS subprocesses, MongoDB Atlas, and `mise` / Python CLI tasks.

## Supervisor and Multi-Page Control Room
scene: containers
reveal: browser, fl.supervisor, fl.control_room, fl.supervisor->fl.control_room, browser->fl.control_room
highlight: fl.supervisor, fl.control_room
camera: browser, fl.supervisor, fl.control_room
caption: Port 8000 serves standalone Workspace (/), Infrastructure (/infra), and Store (/store) pages
evidence: src/mongodb_hackathon/__init__.py:13-66, src/mongodb_hackathon/app.py:306-515, src/mongodb_hackathon/app.py:585-1353, src/mongodb_hackathon/templates/base.html:1-110, src/mongodb_hackathon/static/live-run.js:1-243

`uv run mongodb-hackathon` (wrapped by `mise run server`) spawns two child `uvicorn` processes on `SERVER_HOST=0.0.0.0`. The **Operator Control Room** (`app.py`, port `8000`) renders three standalone pages—`/` Workspace, `/infra` Infrastructure, and `/store` MongoDB Store—linked by a shared `base.html` header and `#live-run-strip` synced via `live-run.js` over `/api/active-run/stream`. It manages `demo_repos` and `experience_memories`, launches and `SIGKILL`s workers, edits/advances paused Step 1 plans, transcribes voice approvals, and proxies target chaos controls.

## Target Deployment Microservice
reveal: fl.target, fl.supervisor->fl.target, fl.control_room->fl.target
highlight: fl.target
camera: fl.supervisor, fl.control_room, fl.target
caption: Port 8001 simulates deployments, silent 202 drops, v2 OpenAPI drift, and active probes
evidence: src/mongodb_hackathon/target_service.py:14, src/mongodb_hackathon/target_service.py:52-70, src/mongodb_hackathon/target_service.py:87-290, src/mongodb_hackathon/config.py:54

The **Target Deployment Service** (`target_service.py`, port `8001`) models a downstream release target in Python dicts. It exposes `/v1/deployments`, `/v2/deployments`, `/openapi.json`, `/health`, `/state`, `GET /verify/{deployment_id}`, `DELETE /deployments/{deployment_id}`, and chaos switches (`normal`, `silent_drop_202`, `drift_v2`, `require_approval_gate`).

## Standalone Crash-Resumable Worker
reveal: fl.worker, fl.control_room->fl.worker, fl.worker->fl.target, fl.worker->github, fl.worker->openai, fl.worker->elevenlabs, fl.worker->telemetry, github, openai, elevenlabs, telemetry
highlight: fl.worker
camera: fl.control_room, fl.worker, fl.target
caption: Detached OS worker processes execute the 5-step pipeline and survive SIGKILL crashes
evidence: src/mongodb_hackathon/worker.py:130-723, src/mongodb_hackathon/app.py:130-147, src/mongodb_hackathon/app.py:628, src/mongodb_hackathon/app.py:699, src/mongodb_hackathon/app.py:753, src/mongodb_hackathon/app.py:948, src/mongodb_hackathon/app.py:989

For run creation, fresh-PID resume, paused `SIGKILL` recovery, crashed-run approval, or rollback, the Control Room spawns `python -m mongodb_hackathon.worker --run-id <id> --step-delay <sec>` with `start_new_session=True`. Separate OS PIDs keep `SIGKILL` authentic: the worker vanishes immediately without cleanup, letting a resumed PID pick up from MongoDB checkpoints without duplicating prior commits or deployments.

## Datastores, Seed, Eval, and Mise Tasks
reveal: atlas, fl.audio_fs, fl.oneshot, fl.control_room->atlas, fl.worker->atlas, fl.worker->fl.audio_fs, fl.control_room->fl.audio_fs, fl.oneshot->atlas, fl.oneshot->github, fl.oneshot->fl.target
highlight: atlas, fl.audio_fs, fl.oneshot
camera: fl.control_room, fl.worker, fl.oneshot, atlas, fl.audio_fs
caption: Atlas persists all durable state; AUDIO_DIR and /static now share the package audio folder
evidence: src/mongodb_hackathon/mongo.py:95-213, src/mongodb_hackathon/worker.py:37, src/mongodb_hackathon/app.py:46-48, src/mongodb_hackathon/app.py:315-316, src/mongodb_hackathon/seed.py:223-272, scripts/run_evals.py:27-193, mise.toml:1-40

**MongoDB Atlas** (`finishline` database) persists `job_runs`, `$jsonSchema`-validated `step_checkpoints`, `demo_repos`, Vector Search `experience_memories`, and TTL `service_events`. On disk, `worker.py` now resolves `AUDIO_DIR = Path(__file__).resolve().parent / "static" / "audio"`, matching `app.py`'s `STATIC_DIR` mount so ElevenLabs MP3 briefings serve cleanly. `mise.toml` standardizes `server`, `walkthrough`, `seed`, `lint`, `typecheck`, `test`, `check`, and `evals` tasks.

# The defining flow end to end

FinishLine pairs prompt-first repository selection and optional `Step-by-Step` pausing with idempotent execution and independent deployment verification.

## Pick repo, compose goal, and stream SSE
scene: containers
only: browser, fl.control_room, fl.worker, atlas, fl.target, github, openai
flow: browser->fl.control_room, fl.control_room->atlas, fl.control_room->fl.worker
highlight: browser, fl.control_room, fl.worker, atlas
camera: browser, fl.control_room, fl.worker, atlas
caption: POST /runs creates a paced or step-by-step JobRun, spawns worker.py, and streams snapshots
evidence: src/mongodb_hackathon/templates/index.html:19-94, src/mongodb_hackathon/templates/index.html:696-738, src/mongodb_hackathon/app.py:585-646, src/mongodb_hackathon/static/live-run.js:187-213

On `GET /`, the operator picks a curated repository from `demo_repos` (or adds one inline), types any release goal (`issue_number=0`) or loads an editable starter chip, chooses pacing (`Fast 0.1s`, `Demo 0.5s` default, `Slow 2.5s`, or `Step-by-Step`), and clicks **Run Release Closer** (`POST /runs`). The Control Room inserts a `JobRun`, spawns a worker PID, and streams live snapshots across `/`, `/infra`, and `/store` via `/api/active-run/stream`.

## Step 1 recall, breakpoint edit, and Step 2 patch
flow: fl.worker->atlas, fl.worker->openai, fl.control_room->openai, fl.worker->github
highlight: fl.worker, fl.control_room, atlas, openai, github
camera: browser, fl.control_room, fl.worker, atlas, github
caption: Vector Search scopes by source_repo; Step-by-Step lets the operator edit FixPlan before Step 2
evidence: src/mongodb_hackathon/worker.py:130-162, src/mongodb_hackathon/worker.py:246-347, src/mongodb_hackathon/mongo.py:343-388, src/mongodb_hackathon/app.py:722-887, src/mongodb_hackathon/templates/index.html:145-180

Step 1 (`step_1_plan`) queries `experience_vector_idx` filtered to `kind=["repo_rule", "github_fix"]` and `source_repo in [run.repo, "*"]`, generates `FixPlan`, and writes checkpoint 1 atomically. In `Step-by-Step` mode, `_pause_if_step_by_step` sets `step_paused=True, paused_after_step=1`; while paused, `POST /runs/{id}/plan` lets the operator edit or re-prompt Step 1 `FixPlan` in Atlas before clicking **Next Step →** (`POST /runs/{id}/advance`). Step 2 (`step_2_github_patch`) reloads the saved `step_1_plan`, creates `finishline/{issue-N|task}-{run_id[:6]}`, and commits `fix_plan.patch_filename`.

## Deploy, adapt v2 drift, verify probe, and finish
flow: fl.worker->fl.target, fl.worker->openai, fl.worker->atlas, fl.worker->github, fl.control_room->atlas, browser->fl.control_room
highlight: fl.worker, fl.target, openai, github, atlas
camera: all
caption: Step 3 probes GET /verify/{id}, adapts 422 drift, and retries; Steps 4-5 open PR and learn on drift
evidence: src/mongodb_hackathon/worker.py:368-718, src/mongodb_hackathon/target_service.py:131-269, src/mongodb_hackathon/github_adapter.py:274-396

In Step 3, `worker.py` checks `GET /health` upfront for `require_approval_gate`, then posts `POST /v1/deployments` with `idempotency_key=f"{run_id}-deploy"`. Under `silent_drop_202`, `GET /verify/{id}` catches `active=False` behind HTTP `202` and retries with the same `idempotency_key`. Under `drift_v2`, `422` triggers `GET /openapi.json` + repo-scoped `drift_playbook` recall + `adapt_to_schema_drift()` onto `POST /v2/deployments`. Once `GET /verify/{id}` returns `active=True`, Step 4 opens the PR and attaches verification comments and labels (on `issue_number`, or directly on the PR when `issue_number == 0`), and Step 5 stamps a `learned-{run_id}` rule scoped to `source_repo=run.repo` whenever drift adaptation occurred before marking the run `COMPLETED`.

## Hard SIGKILL crash and fresh-PID resume
flow: browser->fl.control_room, fl.control_room->fl.worker, fl.control_room->atlas, fl.worker->atlas
highlight: browser, fl.control_room, fl.worker, atlas
camera: browser, fl.control_room, fl.worker, atlas
caption: Any page can SIGKILL a worker PID; resuming skips completed checkpoints safely
evidence: src/mongodb_hackathon/app.py:649-785, src/mongodb_hackathon/worker.py:231-244, src/mongodb_hackathon/worker.py:301-309, src/mongodb_hackathon/worker.py:357-366, src/mongodb_hackathon/worker.py:606-614, src/mongodb_hackathon/templates/base.html:81-82, src/mongodb_hackathon/templates/index.html:129-130, src/mongodb_hackathon/templates/index.html:826-834, src/mongodb_hackathon/static/live-run.js:126-169

From `/` or `#live-run-strip` on `/infra` or `/store`, clicking **SIGKILL Worker** (`POST /runs/{id}/kill`) sends `SIGKILL`, clears `worker_pid`, and marks the run `crashed`. Clicking **Resume Fresh PID** (`/resume`) or **Resume Crashed PID ↺** (`/advance`) spawns a new worker PID that reloads `step_checkpoints`, emits `checkpoint_skipped` for completed steps, and finishes remaining work without duplicate side effects.

# Inside each container

Zooming inside each container shows the new multi-page routes, breakpoint state machine, and target endpoints added under `mh-ju7`.

## Standalone Worker: checkpoints, pause breakpoints, and reload
scene: worker
reveal: wrk.entry, wrk.step1, wrk.pause, wrk.step2, wrk.step3, wrk.step4, wrk.step5, atlas, wrk.entry->wrk.step1, wrk.step1->wrk.pause, wrk.pause->wrk.step2, wrk.step1->wrk.step2, wrk.step2->wrk.step3, wrk.step3->wrk.step4, wrk.step4->wrk.step5, wrk.step1->atlas, wrk.pause->atlas
highlight: wrk.step1, wrk.pause, wrk.step2, atlas
camera: wrk.entry, wrk.step1, wrk.pause, wrk.step2, atlas
caption: execute_job skips completed steps and reloads operator-edited Step 1 plans after pausing
evidence: src/mongodb_hackathon/worker.py:130-162, src/mongodb_hackathon/worker.py:214-218, src/mongodb_hackathon/worker.py:231-366, src/mongodb_hackathon/worker.py:598, src/mongodb_hackathon/worker.py:606-614

`execute_job` marks `worker_pid` and loads `existing_cps` into memory; Steps 1–4 skip cleanly when already at `VERIFIED_TOOK_EFFECT`. In `step_by_step` mode, `_pause_if_step_by_step` pauses cleanly after Step 1 (and after Steps 2 and 3), polling `job_runs` every `0.4s` for `step_paused=False` or `halt_requested=True`. On unpause after Step 1, `worker.py` re-reads `step_1_plan` from Atlas (`cp1_refreshed`) so operator edits to `patch_filename`, `patch_content`, or `deployment_config` take effect in Steps 2–4.

## Standalone Worker: upfront gate, drift adaptation, and rollback
reveal: wrk.gate, wrk.rollback, target, openai, elevenlabs, github, wrk.step3->wrk.gate, wrk.gate->wrk.step3, wrk.gate->wrk.rollback, wrk.step3->target, wrk.step3->openai, wrk.step3->atlas, wrk.gate->elevenlabs, wrk.gate->atlas, wrk.step2->github, wrk.step4->github, wrk.step5->atlas, wrk.pause->wrk.rollback, wrk.step2->wrk.rollback, wrk.step3->wrk.rollback, wrk.rollback->target, wrk.rollback->github
highlight: wrk.step3, wrk.gate, wrk.rollback, target, elevenlabs
camera: wrk.step3, wrk.gate, wrk.rollback, target, github, elevenlabs
caption: Step 3 checks /health upfront for approval gates; _check_halt_or_rollback unwinds Steps 1-3
evidence: src/mongodb_hackathon/worker.py:40-127, src/mongodb_hackathon/worker.py:293, src/mongodb_hackathon/worker.py:353-718, src/mongodb_hackathon/voice.py:15-42, src/mongodb_hackathon/config.py:38

Step 3 now queries `GET /health` before deploying so `require_approval_gate` triggers `_wait_for_operator_approval()` directly (generating `AUDIO_DIR/briefing-{run_id}.mp3` via ElevenLabs `eleven_flash_v2_5`) instead of relying on `422`. `_check_halt_or_rollback` runs between Steps 1–3 (and is invoked by Step 3 whenever `_wait_for_operator_approval` returns `False` on `halt_requested`), deleting target deployments and calling `github.rollback_changes()`. Once execution enters Step 4 (`step_4_github_pr`), halt flags are not re-checked before Step 5 finishes.

## Operator Control Room: 3 standalone pages, repos, plans, and SSE
scene: control_room
reveal: browser, ctrl.ssr, ctrl.repos_mem, ctrl.sandbox, ctrl.lifecycle, ctrl.approve, ctrl.chaos, ctrl.sse, worker_pid, target, atlas, github, openai, scribe, browser->ctrl.ssr, browser->ctrl.repos_mem, browser->ctrl.sandbox, browser->ctrl.lifecycle, browser->ctrl.approve, browser->ctrl.chaos, ctrl.sse->browser, ctrl.repos_mem->github, ctrl.repos_mem->openai, ctrl.repos_mem->atlas, ctrl.sandbox->github, ctrl.lifecycle->worker_pid, ctrl.lifecycle->openai, ctrl.lifecycle->atlas, ctrl.approve->scribe, ctrl.approve->worker_pid, ctrl.approve->atlas, ctrl.chaos->target, atlas->ctrl.sse
highlight: ctrl.ssr, ctrl.repos_mem, ctrl.lifecycle, ctrl.chaos, ctrl.sse
camera: all
caption: app.py splits Workspace, Infra, and Store UIs while synchronizing them over /api/active-run/stream
evidence: src/mongodb_hackathon/app.py:150-224, src/mongodb_hackathon/app.py:358-1353, src/mongodb_hackathon/templates/base.html:12-109, src/mongodb_hackathon/static/live-run.js:126-243

`app.py` renders `GET /` (`index.html`), `GET /infra` (`infra.html`), and `GET /store` (`store.html`) from `base.html`, provides `GET/POST /api/repos` and `GET/POST /api/memories` (embedding rules on creation via OpenAI/fallback), serves `GET /api/target-openapi` with live schema + `contract_diff`, supports `POST /runs/{id}/advance` and `/plan`, transcribes voice approvals via Scribe v2, and pushes snapshots through `GET /api/active-run/stream`.

## Target Deployment Service: v1/v2, active=true/false, and gate
scene: target
reveal: worker, ctrl, tgt.chaos, tgt.v1, tgt.v2, tgt.openapi, tgt.verify, tgt.delete, tgt.state, tgt.gate, ctrl->tgt.chaos, ctrl->tgt.openapi, worker->tgt.chaos, worker->tgt.v1, worker->tgt.v2, worker->tgt.openapi, worker->tgt.verify, worker->tgt.delete, tgt.chaos->tgt.state, tgt.v1->tgt.state, tgt.v2->tgt.state, tgt.verify->tgt.state, tgt.delete->tgt.state, tgt.gate->tgt.chaos
highlight: tgt.v1, tgt.v2, tgt.verify, tgt.gate, tgt.state
camera: all
caption: In-memory _ServiceState tracks active=true/false, request logs, and /health chaos flags
evidence: src/mongodb_hackathon/target_service.py:52-290, src/mongodb_hackathon/app.py:150-224, src/mongodb_hackathon/app.py:1004-1046, src/mongodb_hackathon/worker.py:63, src/mongodb_hackathon/worker.py:414, src/mongodb_hackathon/worker.py:436, src/mongodb_hackathon/worker.py:439, src/mongodb_hackathon/worker.py:455, src/mongodb_hackathon/worker.py:526, src/mongodb_hackathon/worker.py:548

`target_service.py` keeps `chaos_mode`, `deployments` (with `active: bool` and `status: "active" | "dropped_unverified"`), `idempotency_index`, and a 40-entry `request_log` in RAM. Both `app.py` (`/infra` OpenAPI inspector via `/api/target-openapi`) and `worker.py` (`/health` gate check, `/v1` & `/v2` deploys, `/verify/{id}` probes, `/deployments/{id}` deletes) talk directly to `:8001`.

# Where state lives

MongoDB Atlas holds durable state across five collections in `finishline`, while target deployments live in RAM and briefing MP3s share `src/mongodb_hackathon/static/audio`.

## Atlas collections: runs, checkpoints, repos, and memories
scene: data
reveal: ctrl, worker, seed, atlas.job_runs, atlas.step_checkpoints, atlas.experience_memories, atlas.demo_repos, atlas.service_events, ctrl->atlas.job_runs, ctrl->atlas.step_checkpoints, ctrl->atlas.experience_memories, ctrl->atlas.demo_repos, ctrl->atlas.service_events, worker->atlas.job_runs, worker->atlas.step_checkpoints, worker->atlas.experience_memories, worker->atlas.service_events, seed->atlas.demo_repos, seed->atlas.experience_memories
highlight: atlas.step_checkpoints, atlas.experience_memories, atlas.demo_repos
camera: ctrl, worker, seed, atlas
caption: Strict JSON Schema on step_checkpoints, source_repo pre-filters on Vector Search, plus demo_repos
evidence: src/mongodb_hackathon/models.py:49-139, src/mongodb_hackathon/mongo.py:41-257, src/mongodb_hackathon/mongo.py:343-435, src/mongodb_hackathon/seed.py:223-272, src/mongodb_hackathon/app.py:872, src/mongodb_hackathon/app.py:1057-1104, src/mongodb_hackathon/config.py:26

`job_runs` (unvalidated) now tracks `repo`, `step_mode`, `step_paused`, and `paused_after_step`. `step_checkpoints` enforces strict `$jsonSchema` validation, ACID transactions, and unique `(run_id, step_key)` + `idempotency_key` indexes (also updated directly by `POST /runs/{id}/plan`). `demo_repos` stores curated live/dry-run repositories seeded by `seed.py` or registered via `POST /api/repos`, while `experience_memories` indexes `source_repo` alongside `kind` and `status` in `experience_vector_idx` (`dotProduct`, 1536 dims) so rules stay isolated per repository or global `*`. `service_events` powers Atlas Change Streams and expires after 7 days (`expireAfterSeconds=0`).

## Target RAM state, unified audio directory, and design-only collections
reveal: atlas.design_cols, target_mem, audio_fs, ctrl->target_mem, worker->target_mem, worker->audio_fs, ctrl->audio_fs
highlight: target_mem, audio_fs, atlas.design_cols
camera: ctrl, worker, target_mem, audio_fs, atlas.design_cols
caption: Target state resets on restart; AUDIO_DIR and Control Room static mount now match
evidence: src/mongodb_hackathon/target_service.py:52-70, src/mongodb_hackathon/worker.py:37, src/mongodb_hackathon/worker.py:97, src/mongodb_hackathon/voice.py:27-28, src/mongodb_hackathon/app.py:46-48, src/mongodb_hackathon/app.py:315-316, src/mongodb_hackathon/static/live-run.js:15-17, src/mongodb_hackathon/templates/index.html:208-217, src/mongodb_hackathon/templates/store.html:431, docs/hackathon-options.md:57-71

`_ServiceState` clears whenever `:8001` restarts. On disk, `worker.py` writes `briefing-{run_id}.mp3` into `src/mongodb_hackathon/static/audio`, matching FastAPI's `/static` mount. Browser state remains strictly in JS variables (`live-run.js`, `index.html`, and `store.html`), while `delegations`, `policies`, and `action_intents` exist only in `docs/hackathon-options.md`.

# How it runs

FinishLine runs locally via `mise` or `uv` bound to `0.0.0.0`, with no production containers, CI/CD, TLS, or endpoint authentication.

## Local mise tasks, 0.0.0.0 binding, and missing prod infra
scene: deploy
reveal: browser, host.sup, host.ctrl, host.tgt, host.wrk, host.env, atlas, apis, prod_missing, browser->host.ctrl, host.sup->host.ctrl, host.sup->host.tgt, host.ctrl->host.wrk, host.ctrl->host.env, host.wrk->host.env, host.ctrl->atlas, host.wrk->atlas, host.wrk->apis, host.ctrl->apis
highlight: host.sup, host.ctrl, host.tgt, host.env, prod_missing
camera: all
caption: mise.toml standardizes server, seed, check, evals, and walkthrough tasks on local 0.0.0.0 ports
evidence: mise.toml:1-40, src/mongodb_hackathon/__init__.py:13-66, src/mongodb_hackathon/config.py:18-55, src/mongodb_hackathon/agent.py:30, src/mongodb_hackathon/app.py:141-147, src/mongodb_hackathon/app.py:309-314, src/mongodb_hackathon/target_service.py:14-20, src/mongodb_hackathon/target_service.py:111-123, src/mongodb_hackathon/target_service.py:272-289, .env.example:1-32

`mise.toml` defines `server` (`0.0.0.0:8000` + `:8001` via `mongodb-hackathon`), `walkthrough` (`0.0.0.0:8090` via `--bind 0.0.0.0`), `sync`, `seed`, `lint`, `typecheck`, `test`, `check`, and `evals`. Both FastAPI servers leave CORS (`*`) and destructive endpoints unauthenticated, while the Control Room discards worker `stdout`/`stderr` to `DEVNULL` and does not reap `SIGKILL`ed PIDs. Across the codebase, 10 environment variables are absent from `.env.example`: 8 in `config.py` (`MONGODB_DB`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`, `ELEVENLABS_VOICE_ID`, `GITHUB_TOKEN`, `TARGET_SERVICE_URL`, `CONTROL_ROOM_PORT`, `TARGET_SERVICE_PORT`), `LOGFIRE_TOKEN` in `agent.py`, and `WALKTHROUGH_PORT` in `mise.toml`.

# Surprises

Auditing `HEAD` (`8c51030`) against `docs/walkthrough/inventory.md` uncovered concrete code-vs-UI and doc mismatches—each is a candidate follow-up issue.

## Surprise 1: Workspace step keys and compensating_action serialization
scene: control_room
only: browser, ctrl.ssr, ctrl.sse, worker_pid, atlas, browser->ctrl.ssr, atlas->ctrl.sse, ctrl.sse->browser
highlight: browser, ctrl.ssr
camera: browser, ctrl.ssr, worker_pid
caption: index.html matches step_3_deploy_probe & step_5_close_issue instead of worker keys, hiding Steps 3 & 5
evidence: src/mongodb_hackathon/templates/index.html:219-225, src/mongodb_hackathon/templates/index.html:614, src/mongodb_hackathon/templates/index.html:641, src/mongodb_hackathon/worker.py:371, src/mongodb_hackathon/worker.py:694, src/mongodb_hackathon/models.py:64

`VERIFICATION_STEPS` in `templates/index.html` lists keys `"step_3_deploy_probe"` and `"step_5_close_issue"` (titled `"Merge PR & Close Issue"`), whereas `worker.py` saves `"step_3_deploy_and_verify"` and `"step_5_finalize"` (and neither merges the PR nor closes issues). Strict equality `c.step_key === vStep.key` hides Step 3 and Step 5 checkpoint pills and probes on `GET /`. Additionally, `escapeHtml(cp.compensating_action)` renders dict values as `"[object Object]"`.

## Surprise 2: Unguarded dry-run/* lookups on /api/issues and POST /runs
only: browser, ctrl.sandbox, ctrl.lifecycle, github, browser->ctrl.sandbox, ctrl.sandbox->github, browser->ctrl.lifecycle
highlight: ctrl.sandbox, ctrl.lifecycle, github
camera: browser, ctrl.sandbox, ctrl.lifecycle, github
caption: GET /api/issues hits real GitHub for dry-run/* starter repos and returns HTTP 500
evidence: src/mongodb_hackathon/app.py:404-412, src/mongodb_hackathon/app.py:550-558, src/mongodb_hackathon/app.py:598-605, src/mongodb_hackathon/github_adapter.py:147-159, src/mongodb_hackathon/templates/index.html:461

Unlike `GET /`, `GET /api/issues` and `GitHubSandboxAdapter.list_open_issues()` do not skip `dry-run/*` repositories, so selecting `dry-run/payments-webhook` in Workspace calls `GET /repos/dry-run/payments-webhook/issues` and fails with `500`. Similarly, `POST /runs` only exempts `dry-run/finishline-demo-sandbox` (not other `dry-run/*` repos) and omits an `issue_number > 0` check before attempting issue lookup when `issue_body` is empty.

## Surprise 3: Pause button concurrency and /infra gate timing label
only: browser, ctrl.lifecycle, ctrl.chaos, worker_pid, target, browser->ctrl.lifecycle, ctrl.lifecycle->worker_pid, browser->ctrl.chaos, ctrl.chaos->target
highlight: browser, ctrl.lifecycle, ctrl.chaos
camera: browser, ctrl.lifecycle, ctrl.chaos, worker_pid, target
caption: Resume Fresh PID stays enabled while paused (spawning a 2nd PID); /infra says gate runs before Step 4
evidence: src/mongodb_hackathon/templates/index.html:536, src/mongodb_hackathon/app.py:689-720, src/mongodb_hackathon/worker.py:158-162, src/mongodb_hackathon/templates/infra.html:76-80, src/mongodb_hackathon/worker.py:411-430

On `GET /`, `#btn-resume` stays visible whenever `run.step_paused` is true alongside **Next Step →**; clicking **Resume Fresh PID** spawns a second worker PID while the first PID is still polling `step_paused` in `_pause_if_step_by_step`. Separately, `/infra` labels `Approval Gate` as `"Before Step 4"`, whereas `worker.py` checks `GET /health` and pauses inside Step 3 before `/v1/deployments`.

## Surprise 4: Pinned active-run Change Stream, double SSE on /, and static OpenAPI diff
only: browser, ctrl.sse, ctrl.chaos, atlas, target, atlas->ctrl.sse, ctrl.sse->browser, ctrl.chaos->target
highlight: ctrl.sse, ctrl.chaos, browser
camera: browser, ctrl.sse, ctrl.chaos, atlas, target
caption: /api/active-run/stream locks Change Streams to initial run_id; _fetch_target_openapi hardcodes contract_diff
evidence: src/mongodb_hackathon/app.py:187-219, src/mongodb_hackathon/app.py:1275-1316, src/mongodb_hackathon/static/live-run.js:224-228, src/mongodb_hackathon/templates/index.html:675-678, src/mongodb_hackathon/templates/index.html:893-897

In `/api/active-run/stream`, `_pump_changes()` pins `target_to_watch` at connect time, so a new run launched while `/infra` or `/store` is open waits for the 2-second poll fallback instead of immediate Change Stream wakes. On `/`, `live-run.js` auto-connects on `DOMContentLoaded` before `index.html` opens its own stream without listening to `finishline:snapshot`. Also, `_fetch_target_openapi()` returns a static `contract_diff` dict rather than diffing the live `/openapi.json` response.

## Surprise 5: Dead fields, legacy routes, and README naming drift
scene: containers
only: browser, fl.control_room, fl.oneshot, atlas, browser->fl.control_room, fl.control_room->atlas
highlight: fl.control_room, fl.oneshot
camera: browser, fl.control_room, fl.oneshot, atlas
caption: Unused schema enums/fields, duplicated PACING_PRESETS, legacy /runs/{id}/stream, and stale README copy
evidence: src/mongodb_hackathon/models.py:35, src/mongodb_hackathon/models.py:62, src/mongodb_hackathon/models.py:88, src/mongodb_hackathon/models.py:108-112, src/mongodb_hackathon/mongo.py:410-415, src/mongodb_hackathon/app.py:1181-1234, src/mongodb_hackathon/templates/index.html:245-257, src/mongodb_hackathon/agent.py:10, pyproject.toml:10-24, README.md:38-44, src/mongodb_hackathon/github_adapter.py:69

Rounding out the audit: `JobRun.step_gate_approved`, `StepCheckpoint.pre_state`, `StepStatus.BLOCKED_POLICY`, `MongoStore.invalidate_memory()`, and legacy `GET /runs/{run_id}/stream` are unused at runtime; `PACING_PRESETS` is duplicated between Python and JS; `agent.py` imports `logfire` without listing it in `pyproject.toml`; and `README.md` still references single-page button names and `finishline-demo-sandbox` (`github_adapter.py` creates `finishline-sandbox`).

# Where to start reading

Read these ten files/groups in order to trace FinishLine from `mise` and config up through the worker state machine and three-page Control Room UI.

## Reading order: config through multi-page UI
scene: containers
all: true
camera: all
caption: Follow pyproject & mise -> config -> models -> mongo & seed -> target -> agent -> worker -> app & base.html
evidence: pyproject.toml:1-49, mise.toml:1-40, .env.example:1-32, src/mongodb_hackathon/config.py:9-60, src/mongodb_hackathon/__init__.py:13-66, src/mongodb_hackathon/models.py:15-163, src/mongodb_hackathon/mongo.py:26-435, src/mongodb_hackathon/seed.py:15-272, src/mongodb_hackathon/target_service.py:23-290, src/mongodb_hackathon/agent.py:10-231, src/mongodb_hackathon/embeddings.py:12-46, src/mongodb_hackathon/github_adapter.py:16-432, src/mongodb_hackathon/voice.py:15-62, src/mongodb_hackathon/worker.py:40-745, src/mongodb_hackathon/app.py:130-1353, src/mongodb_hackathon/templates/base.html:1-110, src/mongodb_hackathon/static/live-run.js:1-243

Start at the outer entrypoints and move inward:

- **1.** `pyproject.toml` & `mise.toml` — Python 3.14 constraints, dependencies, and `mise` tasks (`server`, `walkthrough`, `seed`, `check`, `evals`).
- **2.** `.env.example` & `src/mongodb_hackathon/config.py` — Required secrets vs 8 code-only `Settings` fields (plus `LOGFIRE_TOKEN` in `agent.py` and `WALKTHROUGH_PORT` in `mise.toml`).
- **3.** `src/mongodb_hackathon/__init__.py` — Dual-port `uvicorn` launcher for `:8000` and `:8001`.
- **4.** `src/mongodb_hackathon/models.py` — Status enums, `PACING_PRESETS`, `DemoRepo`, `JobRun` breakpoints, and Pydantic AI contracts.
- **5.** `src/mongodb_hackathon/mongo.py` & `src/mongodb_hackathon/seed.py` — Strict `$jsonSchema` checkpoints, `source_repo` Vector Search pre-filters, ACID transactions, and starter seeding.
- **6.** `src/mongodb_hackathon/target_service.py` — In-memory `v1`/`v2` contracts, `silent_drop_202`, `drift_v2`, `require_approval_gate`, and `/verify/{id}`.
- **7.** `src/mongodb_hackathon/agent.py` & `src/mongodb_hackathon/embeddings.py` — Structured planning/adaptation agents, LangSmith/Logfire telemetry, and offline fallbacks.
- **8.** `src/mongodb_hackathon/github_adapter.py` & `src/mongodb_hackathon/voice.py` — GitHub REST mutations/rollbacks and ElevenLabs TTS/STT (`issue_number=0` vs issue branching happens in `worker.py`).
- **9.** `src/mongodb_hackathon/worker.py` — 5-step crash-resumable loop, breakpoint reload, probe retries, drift adaptation, and rollback.
- **10.** `src/mongodb_hackathon/app.py`, `templates/base.html` & `static/live-run.js` — Standalone `/`, `/infra`, `/store` routes, repo/memory/plan APIs, and shared SSE strip.
