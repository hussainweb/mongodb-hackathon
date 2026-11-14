"""Lightweight FinishLine worker container exposing /health and /ingest with rate limiting."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_LOCK = threading.Lock()
_WINDOW_START = time.monotonic()
_WINDOW_COUNT = 0
_TOTAL_SERVED = 0
_TOTAL_DROPPED = 0
_HEALTH_PROBES = 0


def _read_config() -> dict[str, Any]:
    api_version = os.getenv("API_VERSION", "v1").strip() or "v1"
    service_name = os.getenv("SERVICE_NAME", "payments-webhook").strip()
    worker_index = int(os.getenv("WORKER_INDEX", "0"))
    env_tier = os.getenv("ENV_TIER", "").strip()
    callback_uri = os.getenv("CALLBACK_URI", "").strip()
    webhook_url = os.getenv("WEBHOOK_URL", "").strip()
    max_rps_raw = os.getenv("MAX_RPS", "").strip()
    rate_limit_raw = os.getenv("RATE_LIMIT", "").strip()

    drift_errors: list[str] = []
    if api_version == "v2":
        if not callback_uri:
            drift_errors.append("missing CALLBACK_URI (v1 WEBHOOK_URL is deprecated)")
        if not max_rps_raw:
            drift_errors.append("missing MAX_RPS (v1 RATE_LIMIT is deprecated)")
        if env_tier not in {"staging", "canary", "production"}:
            drift_errors.append("missing valid ENV_TIER (staging|canary|production)")

    effective_rps = int(max_rps_raw or rate_limit_raw or "120")
    effective_uri = callback_uri or webhook_url or "https://hooks.example.internal/v1/ingest"

    return {
        "api_version": api_version,
        "service_name": service_name,
        "worker_index": worker_index,
        "max_rps": max(1, effective_rps),
        "env_tier": env_tier or "staging",
        "callback_uri": effective_uri,
        "drift_errors": drift_errors,
    }


class WorkerHandler(BaseHTTPRequestHandler):
    """HTTP handler for FinishLine worker health probes and simulated webhook ingestion."""

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        global _HEALTH_PROBES
        cfg = _read_config()
        if self.path.startswith("/health"):
            with _LOCK:
                _HEALTH_PROBES += 1
                probe_num = _HEALTH_PROBES
                served = _TOTAL_SERVED
                dropped = _TOTAL_DROPPED

            silent_drop_first = os.getenv("SILENT_DROP_FIRST_PROBE", "0") == "1"
            if silent_drop_first and probe_num == 1:
                self._send_json(
                    200,
                    {
                        "healthy": False,
                        "active": False,
                        "status": "initializing_dropped",
                        "container_id": socket.gethostname(),
                        "probe_count": probe_num,
                        **cfg,
                    },
                )
                return

            if cfg["drift_errors"]:
                self._send_json(
                    503,
                    {
                        "healthy": False,
                        "active": False,
                        "status": "contract_drift",
                        "container_id": socket.gethostname(),
                        "served": served,
                        "dropped": dropped,
                        **cfg,
                    },
                )
                return

            self._send_json(
                200,
                {
                    "healthy": True,
                    "active": True,
                    "status": "active",
                    "container_id": socket.gethostname(),
                    "served": served,
                    "dropped": dropped,
                    "probe_count": probe_num,
                    **cfg,
                },
            )
            return

        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        global _WINDOW_START, _WINDOW_COUNT, _TOTAL_SERVED, _TOTAL_DROPPED
        if not self.path.startswith("/ingest"):
            self._send_json(404, {"error": "not_found"})
            return

        cfg = _read_config()
        if cfg["drift_errors"]:
            with _LOCK:
                _TOTAL_DROPPED += 1
            self._send_json(
                422,
                {
                    "accepted": False,
                    "error": "API_CONTRACT_DRIFT",
                    "details": cfg["drift_errors"],
                },
            )
            return

        now = time.monotonic()
        with _LOCK:
            if now - _WINDOW_START >= 1.0:
                _WINDOW_START = now
                _WINDOW_COUNT = 0
            if _WINDOW_COUNT < cfg["max_rps"]:
                _WINDOW_COUNT += 1
                _TOTAL_SERVED += 1
                accepted = True
            else:
                _TOTAL_DROPPED += 1
                accepted = False

        if accepted:
            self._send_json(
                200,
                {
                    "accepted": True,
                    "container_id": socket.gethostname(),
                    "max_rps": cfg["max_rps"],
                },
            )
        else:
            self._send_json(
                429,
                {
                    "accepted": False,
                    "reason": "rate_limit_exceeded",
                    "container_id": socket.gethostname(),
                    "max_rps": cfg["max_rps"],
                },
            )


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), WorkerHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
