"""FinishLine package entrypoint launching both target microservice and operator control room."""

from __future__ import annotations

import signal
import subprocess
import sys
import time

from mongodb_hackathon.config import get_settings


def main() -> None:
    """Start target_service (8001) and FinishLine control room (8000) together."""
    settings = get_settings()
    target_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "mongodb_hackathon.target_service:app",
            "--host",
            settings.server_host,
            "--port",
            str(settings.target_service_port),
            "--proxy-headers",
            "--forwarded-allow-ips=*",
        ]
    )
    control_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "mongodb_hackathon.app:app",
            "--host",
            settings.server_host,
            "--port",
            str(settings.control_room_port),
            "--proxy-headers",
            "--forwarded-allow-ips=*",
        ]
    )

    print(
        f"FinishLine running on {settings.server_host}: Control Room -> :{settings.control_room_port} "
        f"| Target Service -> :{settings.target_service_port}",
        flush=True,
    )

    def _shutdown(signum: int, _frame: object) -> None:
        for proc in (control_proc, target_proc):
            if proc.poll() is None:
                proc.send_signal(signum)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while target_proc.poll() is None and control_proc.poll() is None:
            time.sleep(0.5)
    finally:
        for proc in (control_proc, target_proc):
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
