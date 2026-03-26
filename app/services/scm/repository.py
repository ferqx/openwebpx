from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

if TYPE_CHECKING:
    from .types import TokenPayload

import httpx
from fastapi import HTTPException

from .oauth import ScmOAuthService, scm_oauth_service
from .token_store import ScmTokenStore, scm_token_store
from .utils import (
    _normalize_gitlab_base_url,
    _raise_upstream_connect_error,
)


class ScmRepositoryService:
    """SCM 仓库查询服务.

    负责列出用户的仓库和分支信息.
    """

    def __init__(
        self,
        oauth_service: ScmOAuthService = scm_oauth_service,
        token_store: ScmTokenStore = scm_token_store,
    ):
        self.oauth_service = oauth_service
        self.token_store = token_store

    async def fetch_github_installation_repositories(
        self,
        *,
        http_client: httpx.AsyncClient,
        access_token: str,
    ) -> list[dict[str, Any]]:
        """获取 GitHub App 安装的仓库列表."""
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            installations_response = await http_client.get(
                "https://api.github.com/user/installations",
                params={"per_page": 100},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            _raise_upstream_connect_error("GitHub 安装列表查询", exc)
        if installations_response.status_code in {403, 404}:
            return []
        if installations_response.status_code >= 400:
            raise HTTPException(
                installations_response.status_code,
                f"GitHub 安装列表查询失败: {installations_response.text[:200]}",
            )

        installations_payload = (
            installations_response.json() if installations_response.content else {}
        )
        installation_items = (
            installations_payload.get("installations", [])
            if isinstance(installations_payload, dict)
            else []
        )
        if not isinstance(installation_items, list) or not installation_items:
            return []

        repositories: dict[str, dict[str, Any]] = {}
        for installation in installation_items:
            if not isinstance(installation, dict):
                continue
            installation_id = installation.get("id")
            if not isinstance(installation_id, int):
                continue
            try:
                repos_response = await http_client.get(
                    f"https://api.github.com/user/installations/{installation_id}/repositories",
                    params={"per_page": 100},
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitHub 安装仓库查询", exc)
            if repos_response.status_code in {403, 404}:
                continue
            if repos_response.status_code >= 400:
                continue
            repos_payload = repos_response.json() if repos_response.content else {}
            repo_items = (
                repos_payload.get("repositories", [])
                if isinstance(repos_payload, dict)
                else []
            )
            if not isinstance(repo_items, list):
                continue
            for item in repo_items:
                if not isinstance(item, dict):
                    continue
                full_name = item.get("full_name")
                if not isinstance(full_name, str) or not full_name.strip():
                    continue
                repositories[full_name] = {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "full_name": full_name,
                    "default_branch": item.get("default_branch"),
                }
        return list(repositories.values())

    async def fetch_github_user_repositories(
        self,
        *,
        http_client: httpx.AsyncClient,
        access_token: str,
    ) -> list[dict[str, Any]]:
        """获取 GitHub 用户的仓库列表."""
        try:
            response = await http_client.get(
                "https://api.github.com/user/repos",
                params={"sort": "updated", "per_page": 100},
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except httpx.HTTPError as exc:
            _raise_upstream_connect_error("GitHub 仓库查询", exc)
        if response.status_code >= 400:
            raise HTTPException(
                response.status_code,
                f"GitHub 仓库查询失败: {response.text[:200]}",
            )
        payload = response.json() if response.content else []
        if not isinstance(payload, list):
            payload = []
        return [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "full_name": item.get("full_name"),
                "default_branch": item.get("default_branch"),
            }
            for item in payload
            if isinstance(item, dict)
        ]

    async def list_github_repositories(
        self,
        *,
        access_token: str,
        token_payload: TokenPayload,
    ) -> list[dict[str, Any]]:
        """列出 GitHub 仓库，优先使用 GitHub App 安装列表."""
        async with httpx.AsyncClient(timeout=20) as http_client:
            repositories = []
            if token_payload.get("github_token_source") == "github_app":
                repositories = await self.fetch_github_installation_repositories(
                    http_client=http_client,
                    access_token=access_token,
                )
            if not repositories:
                repositories = await self.fetch_github_user_repositories(
                    http_client=http_client,
                    access_token=access_token,
                )
            return repositories

    async def list_gitlab_repositories(
        self,
        *,
        access_token: str,
        gitlab_base_url: str | None,
    ) -> list[dict[str, Any]]:
        """列出 GitLab 仓库."""
        resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
        async with httpx.AsyncClient(timeout=20) as http_client:
            try:
                response = await http_client.get(
                    f"{resolved_base_url}/api/v4/projects",
                    params={
                        "membership": True,
                        "simple": True,
                        "per_page": 100,
                        "order_by": "last_activity_at",
                        "sort": "desc",
                    },
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitLab 仓库查询", exc)
            if response.status_code >= 400:
                raise HTTPException(
                    response.status_code,
                    f"GitLab 仓库查询失败: {response.text[:200]}",
                )
            payload = response.json() if response.content else []
            if not isinstance(payload, list):
                payload = []
            repositories = [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "path_with_namespace": item.get("path_with_namespace"),
                    "default_branch": item.get("default_branch"),
                }
                for item in payload
                if isinstance(item, dict)
            ]
            return repositories

    async def list_github_branches(
        self,
        *,
        repository: str,
        access_token: str,
    ) -> list[dict[str, str]]:
        """列出 GitHub 仓库的分支."""
        async with httpx.AsyncClient(timeout=20) as http_client:
            try:
                response = await http_client.get(
                    f"https://api.github.com/repos/{repository}/branches",
                    params={"per_page": 100},
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {access_token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitHub 分支查询", exc)
            if response.status_code >= 400:
                raise HTTPException(
                    response.status_code,
                    f"GitHub 分支查询失败: {response.text[:200]}",
                )
            payload = response.json() if response.content else []
            if not isinstance(payload, list):
                payload = []
            branches: list[dict[str, str]] = [
                {"name": cast("str", item.get("name"))}
                for item in payload
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ]
            return branches

    async def list_gitlab_branches(
        self,
        *,
        repository: str,
        access_token: str,
        gitlab_base_url: str | None,
    ) -> list[dict[str, str]]:
        """列出 GitLab 仓库的分支."""
        resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
        encoded_repo = quote(repository, safe="")
        async with httpx.AsyncClient(timeout=20) as http_client:
            try:
                response = await http_client.get(
                    f"{resolved_base_url}/api/v4/projects/{encoded_repo}/repository/branches",
                    params={"per_page": 100},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitLab 分支查询", exc)
            if response.status_code >= 400:
                raise HTTPException(
                    response.status_code,
                    f"GitLab 分支查询失败: {response.text[:200]}",
                )
            payload = response.json() if response.content else []
            if not isinstance(payload, list):
                payload = []
            branches: list[dict[str, str]] = [
                {"name": cast("str", item.get("name"))}
                for item in payload
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ]
            return branches

    async def get_github_pr_diff(
        self,
        *,
        repository: str,
        pr_number: int,
        access_token: str,
    ) -> str:
        """获取 GitHub PR 的 diff 内容."""
        async with httpx.AsyncClient(timeout=30) as http_client:
            try:
                response = await http_client.get(
                    f"https://api.github.com/repos/{repository}/pulls/{pr_number}",
                    headers={
                        "Accept": "application/vnd.github.v3.diff",
                        "Authorization": f"Bearer {access_token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitHub PR Diff 查询", exc)
            if response.status_code >= 400:
                raise HTTPException(
                    response.status_code,
                    f"GitHub PR Diff 查询失败: {response.text[:200]}",
                )
            return response.text

    async def get_gitlab_mr_diff(
        self,
        *,
        repository: str,
        mr_iid: int,
        access_token: str,
        gitlab_base_url: str | None,
    ) -> str:
        """获取 GitLab MR 的 diff 内容."""
        resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
        encoded_repo = quote(repository, safe="")
        async with httpx.AsyncClient(timeout=30) as http_client:
            try:
                # GitLab 提供了一个专门的比较接口，或者可以直接获取 raw diff
                response = await http_client.get(
                    f"{resolved_base_url}/api/v4/projects/{encoded_repo}/merge_requests/{mr_iid}/diffs",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitLab MR Diff 查询", exc)
            if response.status_code >= 400:
                raise HTTPException(
                    response.status_code,
                    f"GitLab MR Diff 查询失败: {response.text[:200]}",
                )

            diffs = response.json()
            if not isinstance(diffs, list):
                return ""

            # 将所有文件的 diff 拼接起来
            full_diff = []
            for d in diffs:
                file_path = d.get("new_path") or d.get("old_path")
                diff_content = d.get("diff")
                if file_path and diff_content:
                    full_diff.append(
                        f"--- {file_path}\n+++ {file_path}\n{diff_content}"
                    )

            return "\n".join(full_diff)

    async def post_gitlab_mr_comment(
        self,
        *,
        repository: str,
        mr_iid: int,
        body: str,
        access_token: str,
        gitlab_base_url: str | None,
    ) -> dict[str, Any]:
        """在 GitLab MR 上发表普通评论."""
        resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
        encoded_repo = quote(repository, safe="")
        async with httpx.AsyncClient(timeout=30) as http_client:
            try:
                response = await http_client.post(
                    f"{resolved_base_url}/api/v4/projects/{encoded_repo}/merge_requests/{mr_iid}/notes",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"body": body},
                )
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitLab MR 评论发布", exc)
            if response.status_code >= 400:
                raise HTTPException(
                    response.status_code,
                    f"GitLab MR 评论发布失败: {response.text[:200]}",
                )
            return response.json()

    async def list_gitlab_mr_comments(
        self,
        *,
        repository: str,
        mr_iid: int,
        access_token: str,
        gitlab_base_url: str | None,
    ) -> list[dict[str, Any]]:
        """获取 GitLab MR 的所有普通评论."""
        resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
        encoded_repo = quote(repository, safe="")
        async with httpx.AsyncClient(timeout=30) as http_client:
            try:
                response = await http_client.get(
                    f"{resolved_base_url}/api/v4/projects/{encoded_repo}/merge_requests/{mr_iid}/notes?sort=desc&per_page=50",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitLab MR 评论查询", exc)
            if response.status_code >= 400:
                return []
            return response.json()

    async def update_gitlab_mr_comment(
        self,
        *,
        repository: str,
        mr_iid: int,
        note_id: int,
        body: str,
        access_token: str,
        gitlab_base_url: str | None,
    ) -> dict[str, Any]:
        """更新 GitLab MR 上的已有评论."""
        resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
        encoded_repo = quote(repository, safe="")
        async with httpx.AsyncClient(timeout=30) as http_client:
            try:
                response = await http_client.put(
                    f"{resolved_base_url}/api/v4/projects/{encoded_repo}/merge_requests/{mr_iid}/notes/{note_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"body": body},
                )
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitLab MR 评论更新", exc)
            if response.status_code >= 400:
                raise HTTPException(
                    response.status_code,
                    f"GitLab MR 评论更新失败: {response.text[:200]}",
                )
            return response.json()

    async def register_gitlab_webhook(
        self,
        *,
        repository: str,
        webhook_url: str,
        secret_token: str,
        access_token: str,
        gitlab_base_url: str | None,
    ) -> dict[str, Any]:
        """为 GitLab 项目注册 Webhook."""
        resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
        encoded_repo = quote(repository, safe="")
        async with httpx.AsyncClient(timeout=30) as http_client:
            try:
                response = await http_client.post(
                    f"{resolved_base_url}/api/v4/projects/{encoded_repo}/hooks",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={
                        "url": webhook_url,
                        "secret_token": secret_token,
                        "merge_requests_events": True,
                        "push_events": True,
                        "note_events": False,
                        "enable_ssl_verification": True,
                    },
                )
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitLab Webhook 注册", exc)

            if response.status_code == 409:
                return {"message": "Webhook already exists"}

            if response.status_code >= 400:
                raise HTTPException(
                    response.status_code,
                    f"GitLab Webhook 注册失败: {response.text[:200]}",
                )
            return response.json()


# Global singleton instance
scm_repository_service = ScmRepositoryService()
