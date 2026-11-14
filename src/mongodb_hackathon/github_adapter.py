"""Idempotent GitHub sandbox adapter using GITHUB_TOKEN or authenticated `gh` CLI token."""

from __future__ import annotations

import base64
import subprocess
from typing import Any

import httpx

from mongodb_hackathon.config import Settings, get_settings

GITHUB_API = "https://api.github.com"


def resolve_github_token(settings: Settings | None = None) -> str:
    """Resolve GitHub token from settings or `gh auth token` without logging it."""
    cfg = settings or get_settings()
    if cfg.github_token:
        return cfg.github_token
    try:
        out = subprocess.check_output(["gh", "auth", "token"], text=True, timeout=5)
        return out.strip()
    except OSError, subprocess.SubprocessError:
        return ""


class GitHubSandboxAdapter:
    """Async idempotent client for mutating and rolling back a live GitHub sandbox repo."""

    def __init__(
        self, settings: Settings | None = None, token: str | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self._token = (
            token if token is not None else resolve_github_token(self.settings)
        )

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "finishline-agent/0.1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def ensure_sandbox_repo(self, full_name: str = "") -> dict[str, Any]:
        """Verify or create a public sandbox repo under the authenticated user with seed files."""
        if not self._token:
            raise RuntimeError(
                "No GitHub token available (`GITHUB_TOKEN` or `gh auth login`)"
            )

        async with httpx.AsyncClient(
            base_url=GITHUB_API, headers=self._headers(), timeout=15.0
        ) as client:
            if not full_name:
                user_resp = await client.get("/user")
                user_resp.raise_for_status()
                owner = user_resp.json()["login"]
                full_name = f"{owner}/finishline-sandbox"

            owner, repo_name = full_name.split("/", 1)
            repo_resp = await client.get(f"/repos/{full_name}")
            if repo_resp.status_code == 404:
                create_resp = await client.post(
                    "/user/repos",
                    json={
                        "name": repo_name,
                        "description": "FinishLine Track 3 hackathon live sandbox target repository",
                        "private": False,
                        "auto_init": True,
                    },
                )
                create_resp.raise_for_status()

            await self._seed_sandbox_defaults(client, full_name)
            return {"repo": full_name, "html_url": f"https://github.com/{full_name}"}

    async def _seed_sandbox_defaults(
        self, client: httpx.AsyncClient, full_name: str
    ) -> None:
        """Ensure base service config file, labels, and a sample issue exist in the sandbox."""
        config_resp = await client.get(
            f"/repos/{full_name}/contents/service_config.json"
        )
        if config_resp.status_code == 404:
            content = (
                "{\n"
                '  "service_name": "payments-webhook",\n'
                '  "webhook_url": "https://hooks.example.internal/v1/ingest",\n'
                '  "rate_limit": 120,\n'
                '  "env_tier": "staging"\n'
                "}\n"
            )
            encoded = base64.b64encode(content.encode()).decode()
            await client.put(
                f"/repos/{full_name}/contents/service_config.json",
                json={
                    "message": "chore: add baseline service_config.json",
                    "content": encoded,
                },
            )

        issues_resp = await client.get(
            f"/repos/{full_name}/issues",
            params={"state": "open", "per_page": 5},
        )
        if issues_resp.status_code == 200 and not issues_resp.json():
            await client.post(
                f"/repos/{full_name}/issues",
                json={
                    "title": "Webhook retries drop under burst load in staging",
                    "body": (
                        "Downstream webhook ingestion is dropping burst retries when rate_limit is "
                        "capped at 120. Raise rate_limit to 300, verify deployment takes effect, "
                        "and open a release PR."
                    ),
                    "labels": ["bug"],
                },
            )

    async def get_issue(self, repo: str, issue_number: int) -> dict[str, Any]:
        """Fetch an issue from GitHub."""
        async with httpx.AsyncClient(
            base_url=GITHUB_API, headers=self._headers(), timeout=12.0
        ) as client:
            resp = await client.get(f"/repos/{repo}/issues/{issue_number}")
            resp.raise_for_status()
            return resp.json()

    async def list_open_issues(
        self, repo: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """List open issues (excluding PRs) for the sandbox selector."""
        async with httpx.AsyncClient(
            base_url=GITHUB_API, headers=self._headers(), timeout=12.0
        ) as client:
            resp = await client.get(
                f"/repos/{repo}/issues",
                params={"state": "open", "per_page": limit},
            )
            resp.raise_for_status()
            return [item for item in resp.json() if "pull_request" not in item]

    async def list_repo_labels(self, repo: str) -> list[str]:
        """List live label names in a repository."""
        async with httpx.AsyncClient(
            base_url=GITHUB_API, headers=self._headers(), timeout=12.0
        ) as client:
            resp = await client.get(f"/repos/{repo}/labels", params={"per_page": 50})
            resp.raise_for_status()
            return [str(item["name"]) for item in resp.json()]

    async def ensure_branch(
        self,
        repo: str,
        branch_name: str,
        base_branch: str = "main",
    ) -> dict[str, Any]:
        """Idempotently ensure branch exists; safe to re-run after SIGKILL crash."""
        async with httpx.AsyncClient(
            base_url=GITHUB_API, headers=self._headers(), timeout=12.0
        ) as client:
            ref_resp = await client.get(f"/repos/{repo}/git/ref/heads/{branch_name}")
            if ref_resp.status_code == 200:
                sha = ref_resp.json()["object"]["sha"]
                return {
                    "branch": branch_name,
                    "sha": sha,
                    "created": False,
                    "url": f"https://github.com/{repo}/tree/{branch_name}",
                }

            base_resp = await client.get(f"/repos/{repo}/git/ref/heads/{base_branch}")
            if base_resp.status_code == 404 and base_branch == "main":
                base_resp = await client.get(f"/repos/{repo}/git/ref/heads/master")
            base_resp.raise_for_status()
            base_sha = base_resp.json()["object"]["sha"]

            create_resp = await client.post(
                f"/repos/{repo}/git/refs",
                json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
            )
            create_resp.raise_for_status()
            return {
                "branch": branch_name,
                "sha": base_sha,
                "created": True,
                "url": f"https://github.com/{repo}/tree/{branch_name}",
            }

    async def upsert_file_on_branch(
        self,
        repo: str,
        branch_name: str,
        path: str,
        content: str,
        commit_message: str,
    ) -> dict[str, Any]:
        """Idempotently commit file content to branch; skips commit if identical."""
        async with httpx.AsyncClient(
            base_url=GITHUB_API, headers=self._headers(), timeout=15.0
        ) as client:
            existing_sha: str | None = None
            get_resp = await client.get(
                f"/repos/{repo}/contents/{path}",
                params={"ref": branch_name},
            )
            if get_resp.status_code == 200:
                data = get_resp.json()
                existing_sha = data.get("sha")
                existing_b64 = data.get("content", "").replace("\n", "")
                if existing_b64:
                    decoded = base64.b64decode(existing_b64).decode(errors="replace")
                    if decoded == content:
                        return {
                            "path": path,
                            "commit_sha": existing_sha or "",
                            "changed": False,
                            "url": data.get("html_url", ""),
                        }

            payload: dict[str, Any] = {
                "message": commit_message,
                "content": base64.b64encode(content.encode()).decode(),
                "branch": branch_name,
            }
            if existing_sha:
                payload["sha"] = existing_sha

            put_resp = await client.put(f"/repos/{repo}/contents/{path}", json=payload)
            put_resp.raise_for_status()
            res = put_resp.json()
            return {
                "path": path,
                "commit_sha": res["commit"]["sha"],
                "changed": True,
                "url": res["commit"].get("html_url", ""),
            }

    async def ensure_pull_request(
        self,
        repo: str,
        head_branch: str,
        title: str,
        body: str,
        base_branch: str = "main",
    ) -> dict[str, Any]:
        """Idempotently ensure an open PR exists for head_branch."""
        owner = repo.split("/", 1)[0]
        async with httpx.AsyncClient(
            base_url=GITHUB_API, headers=self._headers(), timeout=15.0
        ) as client:
            existing = await client.get(
                f"/repos/{repo}/pulls",
                params={"state": "open", "head": f"{owner}:{head_branch}"},
            )
            existing.raise_for_status()
            pulls = existing.json()
            if pulls:
                pr = pulls[0]
                return {
                    "pr_number": pr["number"],
                    "html_url": pr["html_url"],
                    "created": False,
                }

            repo_info = await client.get(f"/repos/{repo}")
            if repo_info.status_code == 200:
                base_branch = repo_info.json().get("default_branch", base_branch)

            create_resp = await client.post(
                f"/repos/{repo}/pulls",
                json={
                    "title": title,
                    "body": body,
                    "head": head_branch,
                    "base": base_branch,
                },
            )
            create_resp.raise_for_status()
            pr = create_resp.json()
            return {
                "pr_number": pr["number"],
                "html_url": pr["html_url"],
                "created": True,
            }

    async def ensure_issue_comment(
        self,
        repo: str,
        issue_number: int,
        marker: str,
        body: str,
    ) -> dict[str, Any]:
        """Post a comment once per marker so crash-resume never double-comments."""
        async with httpx.AsyncClient(
            base_url=GITHUB_API, headers=self._headers(), timeout=12.0
        ) as client:
            resp = await client.get(
                f"/repos/{repo}/issues/{issue_number}/comments",
                params={"per_page": 50},
            )
            resp.raise_for_status()
            for comment in resp.json():
                if marker in str(comment.get("body", "")):
                    return {
                        "comment_id": comment["id"],
                        "created": False,
                        "html_url": comment["html_url"],
                    }

            post_resp = await client.post(
                f"/repos/{repo}/issues/{issue_number}/comments",
                json={"body": f"{body}\n\n{marker}"},
            )
            post_resp.raise_for_status()
            created = post_resp.json()
            return {
                "comment_id": created["id"],
                "created": True,
                "html_url": created["html_url"],
            }

    async def apply_verified_label(
        self, repo: str, issue_number: int, label: str = "verified"
    ) -> list[str]:
        """Adapt to repo label taxonomy (verified vs status:verified) and apply label."""
        existing_labels = await self.list_repo_labels(repo)
        chosen = label
        if label not in existing_labels:
            for candidate in (f"status:{label}", "status:verified", "enhancement"):
                if candidate in existing_labels:
                    chosen = candidate
                    break
        async with httpx.AsyncClient(
            base_url=GITHUB_API, headers=self._headers(), timeout=12.0
        ) as client:
            if chosen not in existing_labels:
                await client.post(
                    f"/repos/{repo}/labels",
                    json={"name": chosen, "color": "0e8a16"},
                )
            resp = await client.post(
                f"/repos/{repo}/issues/{issue_number}/labels",
                json={"labels": [chosen]},
            )
            resp.raise_for_status()
            return [str(lbl["name"]) for lbl in resp.json()]

    async def rollback_changes(
        self,
        repo: str,
        branch_name: str = "",
        pr_number: int | None = None,
        issue_number: int | None = None,
        remove_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute compensating rollback on GitHub (close PR, delete branch, remove labels)."""
        actions: list[str] = []
        async with httpx.AsyncClient(
            base_url=GITHUB_API, headers=self._headers(), timeout=12.0
        ) as client:
            if pr_number is not None:
                resp = await client.patch(
                    f"/repos/{repo}/pulls/{pr_number}",
                    json={"state": "closed"},
                )
                if resp.status_code < 400:
                    actions.append(f"closed PR #{pr_number}")
            if branch_name:
                del_resp = await client.delete(
                    f"/repos/{repo}/git/refs/heads/{branch_name}"
                )
                if del_resp.status_code in (200, 204):
                    actions.append(f"deleted branch {branch_name}")
            if issue_number is not None and remove_labels:
                for lbl in remove_labels:
                    r = await client.delete(
                        f"/repos/{repo}/issues/{issue_number}/labels/{lbl}"
                    )
                    if r.status_code < 400:
                        actions.append(f"removed label {lbl}")
        return {"rolled_back": True, "actions": actions}
