# FinishLine — Track 3: *Finish the Job*

**Chaos-resumable GitHub & Service Release Closer built with MongoDB Atlas, Pydantic AI, LangSmith, FastAPI/SSE, and ElevenLabs.**

FinishLine separates **only-sent** from **actually took-effect**, survives hard process kills (`SIGKILL`) without duplicate side effects, adapts mid-run to breaking downstream API contract drift (`v1` -> `v2`) using **MongoDB Atlas Vector Search**, and closes real GitHub Pull Requests + Issue verification evidence.

## Architecture

1. **Operator & Chaos Control Room (`port 8000`, [app.py](src/mongodb_hackathon/app.py))**:
   - Launches & manages standalone OS worker PIDs (`worker.py`), delivers real `SIGKILL` crashes, spawns fresh recovery PIDs, toggles live chaos modes, invalidates/restores Vector Search playbooks, handles Track 1 compensating rollbacks, and streams real-time **MongoDB Atlas Change Streams** via SSE.
2. **Standalone Crash-Resumable Worker ([worker.py](src/mongodb_hackathon/worker.py))**:
   - Executes a 5-stage idempotent workflow persisted via ACID MongoDB transactions (`upsert_checkpoint_atomic`), `$jsonSchema`-validated `step_checkpoints`, unique `(run_id, step_key)` + `idempotency_key` indexes, and TTL `service_events`.
3. **Target Deployment Microservice (`port 8001`, [target_service.py](src/mongodb_hackathon/target_service.py))**:
   - Simulates `normal`, `silent_drop_202` (HTTP `202 Accepted` while `GET /verify/{id}` reveals `active=False`), `drift_v2` (`/v1/deployments` returns `422`, requiring OpenAPI `/v2/deployments` mapping), and `require_approval_gate`.
4. **Pydantic AI Agents + Observability ([agent.py](src/mongodb_hackathon/agent.py))**:
   - OpenAI (`gpt-4.1-mini`) structured planning (`FixPlan`) and drift adaptation (`DriftAdaptationPlan`) with deterministic fallback, **LangSmith** nested `trace(...)` spans, and **Logfire** instrumentation when configured.
5. **ElevenLabs Voice Escalation ([voice.py](src/mongodb_hackathon/voice.py))**:
   - Generates operator TTS briefings (`eleven_flash_v2_5`) on ambiguous policy/drift gates and transcribes operator voice decisions via **Scribe v2** (`scribe_v2`).

## Quickstart

```bash
# 1. Configure .env from .env.example (MONGODB_URI, OPENAI_API_KEY, optional ELEVENLABS_API_KEY)
cp .env.example .env

# 2. Install dependencies
uv sync

# 3. Seed Atlas collections, Vector Search index, and real GitHub issue precedents
uv run python -m mongodb_hackathon.seed

# 4. Launch both Target Service (:8001) and Operator Control Room (:8000)
uv run mongodb-hackathon
```

Open `http://127.0.0.1:8000` in your browser.

## 3-Minute Live Demo Script

1. **Bootstrap GitHub Sandbox:** Click **Bootstrap GitHub Sandbox** in the top bar (creates/uses your public `finishline-demo-sandbox` repo via `gh` CLI token).
2. **Silent-Drop Proof (`silent_drop_202`):** Toggle chaos to `silent_drop_202`, select Issue `#1`, and click **Launch Worker**. Watch Step 3 catch HTTP `202` returning `active=False` on `GET /verify/{id}`, emit `probe_mismatch` via Change Streams, retry with the same `idempotency_key`, and achieve `VERIFIED_TOOK_EFFECT`.
3. **Hard `SIGKILL` Crash & Resume:** Toggle `drift_v2` (or `normal`), launch another run, click **`SIGKILL Worker PID`** mid-run, watch worker PID vanish and status flip to `CRASHED`. Click **`Resume Fresh PID`** — a new OS PID spawns, skips completed checkpoints cleanly, adapts `webhook_url -> callback_uri` / `rate_limit -> max_rps` onto `/v2/deployments`, and opens a verified GitHub PR.
4. **Voice Gate or Track 1 Rollback:** Test **`Halt & Compensating Rollback`** to delete the target deployment and revert the sandbox branch, or invalidate a playbook in the right pane (Track 2 crossover).

## Verification & Evaluation

```bash
uv run ruff check .
uv run ty check
uv run pytest -v
uv run python scripts/run_evals.py
```
