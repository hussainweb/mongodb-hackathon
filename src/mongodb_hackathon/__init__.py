"""FinishLine package entrypoint launching both target microservice and operator control room."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from mongodb_hackathon.config import get_settings

PACKAGE_DIR = Path(__file__).resolve().parent


def _uvicorn_cmd(
    app_import: str, host: str, port: int, *, reload: bool = False
) -> list[str]:
    """Build a uvicorn launch command with optional watchfiles auto-reload."""
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        app_import,
        "--host",
        host,
        "--port",
        str(port),
        "--proxy-headers",
        "--forwarded-allow-ips=*",
    ]
    if reload:
        cmd.extend(
            [
                "--reload",
                "--reload-dir",
                str(PACKAGE_DIR),
                "--reload-include",
                "*.py",
                "--reload-include",
                "*.html",
                "--reload-include",
                "*.js",
                "--reload-include",
                "*.css",
            ]
        )
    return cmd


def main(argv: list[str] | None = None) -> None:
    """Start target_service (8001) and FinishLine control room (8000) together."""
    args = sys.argv[1:] if argv is None else argv
    reload_enabled = "--reload" in args or os.getenv("FINISHLINE_RELOAD") == "1"
    settings = get_settings()
    target_proc = subprocess.Popen(
        _uvicorn_cmd(
            "mongodb_hackathon.target_service:app",
            settings.server_host,
            settings.target_service_port,
            reload=reload_enabled,
        )
    )
    control_proc = subprocess.Popen(
        _uvicorn_cmd(
            "mongodb_hackathon.app:app",
            settings.server_host,
            settings.control_room_port,
            reload=reload_enabled,
        )
    )

    mode = " [reload]" if reload_enabled else ""
    print(
        f"FinishLine{mode} running on {settings.server_host}: Control Room -> :{settings.control_room_port} "
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
