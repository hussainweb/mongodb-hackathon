"""OpenTofu + Docker execution, independent health verification, and rollback adapter."""

from __future__ import annotations

import asyncio
import json
import os
import posixpath
import re
import shutil
from pathlib import Path
from typing import Any

import httpx

from mongodb_hackathon.github_adapter import (
    SAMPLE_SPECS,
    GitHubSandboxAdapter,
    load_sample_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
INFRA_TEMPLATE_DIR = REPO_ROOT / "infra" / "template"
WORKSPACES_ROOT = REPO_ROOT / ".finishline_workspaces"


def _safe_slug(repo: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", repo.lower()).strip("-")
    return (slug or "finishline-demo")[:32]


def workspace_dir_for_repo(repo: str) -> Path:
    """Return deterministic local OpenTofu workspace path for a repository."""
    return WORKSPACES_ROOT / _safe_slug(repo)


def _clear_stale_lock(ws_dir: Path) -> bool:
    """Remove stale OpenTofu state lock if left behind by a SIGKILLed worker."""
    lock_file = ws_dir / ".terraform.tfstate.lock.info"
    if not lock_file.exists():
        return False
    lock_file.unlink(missing_ok=True)
    return True


def _seed_cached_providers(ws_dir: Path) -> None:
    """Reuse pre-downloaded provider binaries from infra/template/.terraform when present."""
    src_tf = INFRA_TEMPLATE_DIR / ".terraform"
    dst_tf = ws_dir / ".terraform"
    if src_tf.exists() and not dst_tf.exists():
        shutil.copytree(src_tf, dst_tf, dirs_exist_ok=True)
    src_lock = INFRA_TEMPLATE_DIR / ".terraform.lock.hcl"
    dst_lock = ws_dir / ".terraform.lock.hcl"
    if src_lock.exists() and not dst_lock.exists():
        shutil.copy2(src_lock, dst_lock)


async def _run_tofu(
    ws_dir: Path,
    args: list[str],
    timeout: float = 45.0,
) -> tuple[int, str, str]:
    """Execute `tofu` subprocess in ws_dir with non-interactive stdin."""
    env = dict(os.environ)
    env["TF_IN_AUTOMATION"] = "1"
    proc = await asyncio.create_subprocess_exec(
        "tofu",
        f"-chdir={ws_dir}",
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=False,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", f"tofu {' '.join(args)} timed out after {timeout}s"
    return (
        proc.returncode or 0,
        out_b.decode(errors="replace"),
        err_b.decode(errors="replace"),
    )


async def prepare_workspace(
    github: GitHubSandboxAdapter,
    repo: str,
    branch_name: str,
    tf_dir: str,
    patch_filename: str,
    patch_content: str,
) -> tuple[Path, dict[str, str]]:
    """Sync repo's discovered OpenTofu files into local workspace and return prior file snapshot."""
    ws_dir = workspace_dir_for_repo(repo)
    ws_dir.mkdir(parents=True, exist_ok=True)
    _seed_cached_providers(ws_dir)

    # Capture previous workspace files before overwriting so Track 1 rollback can revert cleanly
    pre_files: dict[str, str] = {}
    for existing in ws_dir.glob("*.tf*"):
        if existing.is_file() and existing.name != ".terraform.lock.hcl":
            pre_files[existing.name] = existing.read_text(encoding="utf-8")

    norm_dir = tf_dir.strip("/")
    norm_dir = "" if norm_dir in {"", "."} else norm_dir

    repo_files = await github.list_repo_files(repo, ref=branch_name)
    for rel_path in repo_files:
        if not rel_path.endswith((".tf", ".tfvars")):
            continue
        parent = posixpath.dirname(rel_path)
        if norm_dir and parent != norm_dir:
            continue
        if not norm_dir and parent != "":
            continue
        content = await github.read_repo_file(repo, rel_path, ref=branch_name)
        if content:
            local_name = posixpath.basename(rel_path)
            (ws_dir / local_name).write_text(content, encoding="utf-8")
            if local_name not in pre_files:
                # Baseline fallback from main branch / template
                baseline = await github.read_repo_file(repo, rel_path)
                if baseline:
                    pre_files[local_name] = baseline

    # Ensure patch_content is always applied locally even in dry-run mode
    if patch_filename.endswith((".tf", ".tfvars")):
        (ws_dir / posixpath.basename(patch_filename)).write_text(
            patch_content, encoding="utf-8"
        )

    # If no .tf files were retrieved (e.g., brand-new repo), fall back to baseline template
    if not list(ws_dir.glob("*.tf")):
        for name in ("main.tf", "variables.tf", "outputs.tf"):
            tpl = INFRA_TEMPLATE_DIR / name
            if tpl.exists():
                (ws_dir / name).write_text(tpl.read_text(encoding="utf-8"), encoding="utf-8")

    return ws_dir, pre_files


async def apply_opentofu(
    ws_dir: Path,
    repo: str,
    worker_image: str = "finishline-worker:v1",
    use_v2_env: bool = False,
    silent_drop_first_probe: bool = False,
    extra_vars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run `tofu init` + `tofu apply` safely and return parsed `workers` output."""
    _clear_stale_lock(ws_dir)

    if not (ws_dir / ".terraform").exists():
        rc, out, err = await _run_tofu(ws_dir, ["init", "-input=false"])
        if rc != 0:
            raise RuntimeError(f"tofu init failed ({rc}): {err or out}")

    # Pick up any *.tfvars present in the workspace automatically
    var_file_args: list[str] = []
    for vf in sorted(ws_dir.glob("*.tfvars")):
        var_file_args.append(f"-var-file={vf.name}")

    var_args = [
        f"-var=run_prefix={_safe_slug(repo)}",
        f"-var=repo_slug={repo}",
        f"-var=worker_image={worker_image}",
        f"-var=use_v2_env={'true' if use_v2_env else 'false'}",
        f"-var=silent_drop_first_probe={'true' if silent_drop_first_probe else 'false'}",
    ]
    for k, v in (extra_vars or {}).items():
        var_args.append(f"-var={k}={v}")

    rc, out, err = await _run_tofu(
        ws_dir,
        ["apply", "-auto-approve", "-input=false", *var_file_args, *var_args],
        timeout=60.0,
    )
    if rc != 0:
        # Retry once if init/provider lock file needs refresh
        rc2, out2, err2 = await _run_tofu(ws_dir, ["init", "-input=false", "-upgrade=false"])
        if rc2 == 0:
            rc, out, err = await _run_tofu(
                ws_dir,
                ["apply", "-auto-approve", "-input=false", *var_file_args, *var_args],
                timeout=60.0,
            )
        else:
            err = err or err2 or out2
    if rc != 0:
        raise RuntimeError(f"tofu apply failed ({rc}): {err or out}")

    rc_out, raw_json, err_out = await _run_tofu(ws_dir, ["output", "-json", "workers"])
    workers: list[dict[str, Any]] = []
    if rc_out == 0 and raw_json.strip():
        parsed = json.loads(raw_json)
        if isinstance(parsed, list):
            workers = parsed
    return {"workers": workers, "stdout": out[-1000:], "stderr": err_out[-400:]}


async def probe_workers(
    workers: list[dict[str, Any]],
    expected_count: int = 1,
) -> dict[str, Any]:
    """Independently probe /health on every OpenTofu-managed Docker container."""
    if len(workers) < expected_count:
        return {
            "healthy": False,
            "active": False,
            "reason": f"expected {expected_count} containers, found {len(workers)}",
            "workers": [],
            "drift_errors": [],
        }

    results: list[dict[str, Any]] = []
    drift_errors: list[str] = []
    all_healthy = True

    async with httpx.AsyncClient(timeout=3.0) as client:
        for w in workers:
            url = str(w.get("url", "")).rstrip("/")
            if not url:
                all_healthy = False
                continue
            last_exc: httpx.HTTPError | None = None
            resp: httpx.Response | None = None
            for _ in range(8):
                try:
                    resp = await client.get(f"{url}/health")
                    last_exc = None
                    break
                except httpx.HTTPError as exc:
                    last_exc = exc
                    await asyncio.sleep(0.25)

            if resp is None:
                all_healthy = False
                results.append(
                    {
                        "name": w.get("name"),
                        "container_id": w.get("container_id"),
                        "port": w.get("port"),
                        "url": url,
                        "healthy": False,
                        "active": False,
                        "error": str(last_exc or "unreachable"),
                    }
                )
                continue

            data = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            is_ok = (
                resp.status_code == 200
                and bool(data.get("active"))
                and bool(data.get("healthy"))
            )
            if not is_ok:
                all_healthy = False
            if resp.status_code == 503 or data.get("status") == "contract_drift":
                drift_errors.extend(data.get("drift_errors", ["v2 contract drift"]))
            results.append(
                {
                    "name": w.get("name"),
                    "container_id": w.get("container_id"),
                    "port": w.get("port"),
                    "url": url,
                    "http_status": resp.status_code,
                    **data,
                }
            )

    return {
        "healthy": all_healthy and len(results) >= expected_count,
        "active": all_healthy and len(results) >= expected_count,
        "workers": results,
        "drift_errors": sorted(set(drift_errors)),
        "api_version": results[0].get("api_version", "v1") if results else "v1",
        "max_rps": sum(int(r.get("max_rps", 0) or 0) for r in results),
        "worker_count": len(results),
    }


async def rollback_opentofu(
    repo: str,
    pre_files: dict[str, str],
) -> str:
    """Restore pre-run OpenTofu files (or destroy if none existed) for Track 1 rollback."""
    ws_dir = workspace_dir_for_repo(repo)
    if not ws_dir.exists():
        return "no local OpenTofu workspace to roll back"

    _clear_stale_lock(ws_dir)
    if pre_files:
        for fname, content in pre_files.items():
            (ws_dir / fname).write_text(content, encoding="utf-8")
        await apply_opentofu(ws_dir, repo=repo)
        return f"restored OpenTofu config in {ws_dir.name} and re-applied baseline containers"

    rc, out, err = await _run_tofu(ws_dir, ["destroy", "-auto-approve", "-input=false"])
    if rc != 0:
        return f"tofu destroy warning ({rc}): {err or out}"
    return f"destroyed ephemeral OpenTofu containers in {ws_dir.name}"


async def inspect_live_docker_workers(simulate_traffic: bool = False) -> dict[str, Any]:
    """Inspect running FinishLine-managed Docker containers and optionally send a live traffic tick."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "ps",
        "--filter",
        "label=finishline.managed=true",
        "--format",
        "{{json .}}",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, _ = await proc.communicate()
    if proc.returncode != 0:
        return {"workers": [], "total_capacity_rps": 0, "traffic": None}

    raw_lines = [ln.strip() for ln in out_b.decode(errors="replace").splitlines() if ln.strip()]
    workers: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=1.5) as client:
        for ln in raw_lines:
            try:
                info = json.loads(ln)
            except json.JSONDecodeError:
                continue
            ports_str = str(info.get("Ports", ""))
            port_match = re.search(r"127\.0\.0\.1:(\d+)->8080/tcp", ports_str)
            if not port_match:
                port_match = re.search(r":(\d+)->8080/tcp", ports_str)
            if not port_match:
                continue
            port = int(port_match.group(1))
            url = f"http://127.0.0.1:{port}"
            health: dict[str, Any] = {}
            try:
                r = await client.get(f"{url}/health")
                if r.headers.get("content-type", "").startswith("application/json"):
                    health = r.json()
            except httpx.HTTPError:
                health = {"healthy": False, "active": False}

            workers.append(
                {
                    "name": info.get("Names", ""),
                    "container_id": str(info.get("ID", ""))[:12],
                    "port": port,
                    "url": url,
                    "state": info.get("State", "running"),
                    "healthy": bool(health.get("healthy", False)),
                    "active": bool(health.get("active", False)),
                    "max_rps": int(health.get("max_rps", 120) or 120),
                    "api_version": health.get("api_version", "v1"),
                    "env_tier": health.get("env_tier", "staging"),
                    "service_name": health.get("service_name", "payments-webhook"),
                }
            )

    traffic: dict[str, Any] | None = None
    if simulate_traffic and workers:
        delivered = 0
        dropped = 0
        # Probe real containers with 6 concurrent webhook requests to show real capacity vs drops
        async with httpx.AsyncClient(timeout=1.5) as client:
            for idx in range(6):
                target = workers[idx % len(workers)]
                try:
                    resp = await client.post(f"{target['url']}/ingest", json={"seq": idx})
                    if resp.status_code == 200:
                        delivered += 1
                    else:
                        dropped += 1
                except httpx.HTTPError:
                    dropped += 1
        traffic = {"sent": 6, "delivered": delivered, "dropped": dropped}

    return {
        "workers": sorted(workers, key=lambda w: str(w.get("name", ""))),
        "total_capacity_rps": sum(w["max_rps"] for w in workers if w["active"]),
        "traffic": traffic,
    }


async def launch_sample_baseline(
    sample_id: str,
    repo_slug: str = "",
) -> dict[str, Any]:
    """Copy a sample's OpenTofu config into its workspace and launch its baseline Docker worker(s)."""
    if sample_id not in SAMPLE_SPECS:
        raise ValueError(f"Unknown sample '{sample_id}'")
    spec = SAMPLE_SPECS[sample_id]
    target_repo = repo_slug.strip() or str(spec["dry_run_repo"])
    ws_dir = workspace_dir_for_repo(target_repo)
    ws_dir.mkdir(parents=True, exist_ok=True)
    _seed_cached_providers(ws_dir)

    tf_prefix = str(spec["tf_dir"]).strip("/") + "/"
    sample_files = load_sample_files(sample_id)
    for rel_path, content in sample_files.items():
        if rel_path.startswith(tf_prefix) and rel_path.endswith((".tf", ".tfvars")):
            local_name = posixpath.basename(rel_path)
            (ws_dir / local_name).write_text(content, encoding="utf-8")

    apply_res = await apply_opentofu(
        ws_dir=ws_dir,
        repo=target_repo,
        worker_image="finishline-worker:v1",
        extra_vars={
            "worker_count": int(spec["worker_count"]),
            "max_rps": int(spec["max_rps"]),
            "service_name": str(spec["service_name"]),
            "env_tier": str(spec["env_tier"]),
        },
    )
    probe = await probe_workers(
        apply_res.get("workers", []),
        expected_count=int(spec["worker_count"]),
    )
    topology = await inspect_live_docker_workers(simulate_traffic=False)
    return {
        "sample_id": sample_id,
        "repo": target_repo,
        "workspace": str(ws_dir),
        "probe": probe,
        "topology": topology,
    }


async def stop_sample_baseline(
    sample_id: str,
    repo_slug: str = "",
) -> dict[str, Any]:
    """Destroy OpenTofu-managed Docker containers for a sample workspace."""
    if sample_id not in SAMPLE_SPECS:
        raise ValueError(f"Unknown sample '{sample_id}'")
    spec = SAMPLE_SPECS[sample_id]
    target_repo = repo_slug.strip() or str(spec["dry_run_repo"])
    msg = await rollback_opentofu(target_repo, pre_files={})
    topology = await inspect_live_docker_workers(simulate_traffic=False)
    return {"sample_id": sample_id, "repo": target_repo, "message": msg, "topology": topology}
