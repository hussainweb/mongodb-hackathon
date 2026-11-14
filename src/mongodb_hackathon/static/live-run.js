/**
 * FinishLine Shared Live Run Strip & Active Run SSE Controller
 * Connects /infra and /store (and workspace) to real-time MongoDB Atlas run state.
 */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.FinishLineLiveRun = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  let activeEventSource = null;
  let currentSnapshot = null;
  let activeOptions = {};

  const STEP_TITLES = {
    1: "Diagnose issue & retrieve Vector Search experience",
    2: "Create GitHub branch & commit config patch",
    3: "Deploy to Target Service & verify probe",
    4: "Open GitHub Pull Request & summarize verification",
    5: "Close issue & record lessons in Atlas",
  };

  function escapeHtml(text) {
    return String(text || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function formatStatus(status) {
    return String(status || "idle").replaceAll("_", " ");
  }

  function badgeClass(status) {
    const s = String(status || "").toLowerCase();
    if (s === "completed" || s === "verified_took_effect") return "badge-ok";
    if (s === "awaiting_approval" || s === "sent_unverified") return "badge-warn";
    if (s === "crashed" || s === "failed" || s === "rolled_back" || s === "blocked_policy") return "badge-danger";
    if (s === "running" || s === "adapted" || s === "drifted") return "badge-info";
    return "badge-neutral";
  }

  function updateLiveRunStrip(snapshot) {
    currentSnapshot = snapshot;
    const run = snapshot ? snapshot.run : null;

    // Update Topbar run indicator if present
    const navText = document.getElementById("nav-run-status-text");
    const navDot = document.getElementById("nav-pulse-dot");
    if (navText) {
      if (run) {
        navText.textContent = `${run.run_id} · ${formatStatus(run.status)}`;
      } else {
        navText.textContent = "No active run";
      }
    }
    if (navDot) {
      navDot.className = "pulse-dot";
      if (run) {
        const s = String(run.status || "").toLowerCase();
        if (s === "running") navDot.classList.add("running");
        else if (s === "awaiting_approval") navDot.classList.add("awaiting");
        else if (s === "crashed" || s === "failed" || s === "rolled_back") navDot.classList.add("crashed");
        else if (s === "completed") navDot.classList.add("completed");
      }
    }

    const stripEl = document.getElementById("live-run-strip");
    if (!stripEl) return;

    const emptyBox = document.getElementById("strip-empty");
    const activeBox = document.getElementById("strip-active");
    if (!run) {
      if (emptyBox) emptyBox.classList.remove("hidden");
      if (activeBox) activeBox.classList.add("hidden");
      return;
    }

    if (emptyBox) emptyBox.classList.add("hidden");
    if (activeBox) activeBox.classList.remove("hidden");

    // Metadata chips
    const idEl = document.getElementById("strip-run-id");
    if (idEl) idEl.textContent = run.run_id;

    const repoEl = document.getElementById("strip-repo");
    if (repoEl) repoEl.textContent = run.repo || "dry-run/finishline-demo-sandbox";

    const badgeEl = document.getElementById("strip-status-badge");
    if (badgeEl) {
      badgeEl.textContent = formatStatus(run.status);
      badgeEl.className = "badge " + badgeClass(run.status);
    }

    const stepEl = document.getElementById("strip-step");
    if (stepEl) {
      const stepSeq = run.current_step || 1;
      const stepTitle = STEP_TITLES[stepSeq] || `Step ${stepSeq}`;
      const pausedSuffix = run.step_paused ? " (Paused at breakpoint)" : "";
      stepEl.textContent = `Step ${stepSeq}/5: ${stepTitle}${pausedSuffix}`;
    }

    const pidEl = document.getElementById("strip-pid");
    if (pidEl) {
      pidEl.textContent = run.worker_pid ? `PID ${run.worker_pid}` : (run.step_paused ? "paused" : "stopped");
    }

    const prEl = document.getElementById("strip-pr-link");
    if (prEl) {
      if (run.pr_url) {
        prEl.innerHTML = `<a href="${escapeHtml(run.pr_url)}" target="_blank" class="nav-ext" style="font-weight: 500;">PR #${escapeHtml(run.pr_url.split("/").pop())} ↗</a>`;
      } else {
        prEl.innerHTML = "";
      }
    }

    // Action buttons
    const btnAdvance = document.getElementById("strip-btn-advance");
    const btnKill = document.getElementById("strip-btn-kill");
    const s = String(run.status || "").toLowerCase();

    if (btnAdvance) {
      const showAdvance = run.step_paused || s === "crashed";
      btnAdvance.classList.toggle("hidden", !showAdvance);
      if (run.step_paused) {
        btnAdvance.textContent = "Advance Step ⏭";
      } else if (s === "crashed") {
        btnAdvance.textContent = "Resume Crashed PID ↺";
      }
    }

    if (btnKill) {
      const showKill = s === "running" && Boolean(run.worker_pid);
      btnKill.classList.toggle("hidden", !showKill);
    }
  }

  async function advanceLiveRun(runId, stepDelay) {
    const id = runId || (currentSnapshot && currentSnapshot.run ? currentSnapshot.run.run_id : "");
    if (!id) return null;
    const body = stepDelay !== undefined ? { step_delay: stepDelay } : {};
    const resp = await fetch(`/runs/${id}/advance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      console.warn("Failed to advance run:", resp.statusText);
      return null;
    }
    const data = await resp.json();
    return data;
  }

  async function killLiveRun(runId) {
    const id = runId || (currentSnapshot && currentSnapshot.run ? currentSnapshot.run.run_id : "");
    if (!id) return null;
    const resp = await fetch(`/runs/${id}/kill`, { method: "POST" });
    if (!resp.ok) {
      console.warn("Failed to kill run:", resp.statusText);
      return null;
    }
    const data = await resp.json();
    return data;
  }

  async function fetchActiveRunSnapshot(runId) {
    const url = runId ? `/api/active-run?run_id=${encodeURIComponent(runId)}` : "/api/active-run";
    try {
      const resp = await fetch(url);
      if (resp.ok) {
        const snap = await resp.json();
        updateLiveRunStrip(snap);
        document.dispatchEvent(new CustomEvent("finishline:snapshot", { detail: snap }));
        return snap;
      }
    } catch (err) {
      console.warn("Error fetching active run snapshot:", err);
    }
    return null;
  }

  function connectLiveRun(options) {
    activeOptions = options || {};
    const runId = activeOptions.runId || "";

    if (activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
    }

    const streamUrl = runId
      ? `/api/active-run/stream?run_id=${encodeURIComponent(runId)}`
      : "/api/active-run/stream";

    activeEventSource = new EventSource(streamUrl);

    activeEventSource.addEventListener("snapshot", function (ev) {
      try {
        const snap = JSON.parse(ev.data);
        updateLiveRunStrip(snap);
        document.dispatchEvent(new CustomEvent("finishline:snapshot", { detail: snap }));
        if (typeof activeOptions.onSnapshot === "function") {
          activeOptions.onSnapshot(snap);
        }
      } catch (err) {
        console.error("Failed to parse SSE snapshot:", err);
      }
    });

    activeEventSource.onerror = function () {
      const navDot = document.getElementById("nav-pulse-dot");
      if (navDot) navDot.className = "pulse-dot";
    };

    return activeEventSource;
  }

  // Auto-connect on page load only when operator live strip exists
  document.addEventListener("DOMContentLoaded", function () {
    const stripEl = document.getElementById("live-run-strip");
    if (!stripEl) return;
    const requestedRunId = stripEl.getAttribute("data-initial-run-id") || "";
    connectLiveRun({ runId: requestedRunId });
  });

  return {
    connectLiveRun: connectLiveRun,
    advanceLiveRun: advanceLiveRun,
    killLiveRun: killLiveRun,
    fetchActiveRunSnapshot: fetchActiveRunSnapshot,
    updateLiveRunStrip: updateLiveRunStrip,
    getSnapshot: function () {
      return currentSnapshot;
    },
    formatStatus: formatStatus,
    badgeClass: badgeClass,
    escapeHtml: escapeHtml,
  };
});
