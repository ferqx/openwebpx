from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from typing import Any, Literal
from urllib.parse import quote, urlparse

import httpx
from aegra_api.api.runs import create_run
from aegra_api.core.orm import Thread as ThreadORM
from aegra_api.core.orm import _get_session_maker
from aegra_api.models.auth import User as AuthUser
from aegra_api.models.runs import RunCreate
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.routers.scm import (
    _normalize_gitlab_base_url,
    _normalize_scm_provider,
    _resolve_scm_access_token,
)

router = APIRouter()
public_router = APIRouter()

ReviewTrigger = Literal["pr_open", "push"]
AutoReviewMode = Literal["follow_global", "enabled", "disabled"]

DEFAULT_REVIEW_TRIGGER: ReviewTrigger = "pr_open"
DEFAULT_GLOBAL_AUTO_REVIEW_ENABLED = False
DEFAULT_REVIEW_GRAPH_ID = os.getenv(
    "OPENWEBPX_DEFAULT_TASK_GRAPH_ID", "build_app_agent_v3"
)
CODE_REVIEW_WEBHOOK_PATH = "/integrations/code-review/webhook"

PROFILE_UPSERT_SQL = """
INSERT INTO code_review_profiles
(
  user_id,
  auto_review_enabled,
  default_trigger,
  updated_at,
  updated_by
)
VALUES
(
  :user_id,
  :auto_review_enabled,
  :default_trigger,
  :updated_at,
  :updated_by
)
ON CONFLICT (user_id) DO UPDATE
SET
  auto_review_enabled = EXCLUDED.auto_review_enabled,
  default_trigger = EXCLUDED.default_trigger,
  updated_at = EXCLUDED.updated_at,
  updated_by = EXCLUDED.updated_by
"""

PROFILE_SELECT_SQL = """
SELECT
  user_id,
  auto_review_enabled,
  default_trigger,
  updated_at,
  updated_by
FROM code_review_profiles
WHERE user_id = :user_id
LIMIT 1
"""

PROFILE_LIST_BY_TRIGGER_SQL = """
SELECT
  user_id,
  auto_review_enabled,
  default_trigger,
  updated_at,
  updated_by
FROM code_review_profiles
WHERE auto_review_enabled = TRUE
  AND default_trigger = :default_trigger
"""

REPO_SETTING_UPSERT_SQL = """
INSERT INTO code_review_repo_settings
(
  setting_id,
  user_id,
  provider,
  gitlab_base_url,
  repository,
  auto_review,
  trigger,
  updated_at,
  updated_by
)
VALUES
(
  :setting_id,
  :user_id,
  :provider,
  :gitlab_base_url,
  :repository,
  :auto_review,
  :trigger,
  :updated_at,
  :updated_by
)
ON CONFLICT (user_id, provider, gitlab_base_url, repository) DO UPDATE
SET
  auto_review = EXCLUDED.auto_review,
  trigger = EXCLUDED.trigger,
  updated_at = EXCLUDED.updated_at,
  updated_by = EXCLUDED.updated_by
"""

REPO_SETTING_LIST_SQL = """
SELECT
  setting_id,
  user_id,
  provider,
  gitlab_base_url,
  repository,
  auto_review,
  trigger,
  updated_at,
  updated_by
FROM code_review_repo_settings
WHERE user_id = :user_id
ORDER BY updated_at DESC
"""

REPO_SETTING_DELETE_SQL = """
DELETE FROM code_review_repo_settings
WHERE user_id = :user_id
  AND provider = :provider
  AND gitlab_base_url IS NOT DISTINCT FROM :gitlab_base_url
  AND repository = :repository
"""

REPO_SETTING_MATCH_SQL = """
SELECT
  setting_id,
  user_id,
  provider,
  gitlab_base_url,
  repository,
  auto_review,
  trigger,
  updated_at,
  updated_by
FROM code_review_repo_settings
WHERE provider = :provider
  AND repository = :repository
  AND gitlab_base_url IS NOT DISTINCT FROM :gitlab_base_url
"""


@dataclass
class WebhookEventContext:
    provider: Literal["github", "gitlab"]
    trigger: ReviewTrigger
    repository: str
    branch: str
    gitlab_base_url: str | None
    title: str
    event_name: str
    payload: dict[str, Any]


@dataclass
class WebhookSyncResult:
    provider: Literal["github", "gitlab"]
    repository: str
    enabled: bool
    ok: bool
    mode: Literal["auto", "manual"]
    message: str
    webhook_url: str | None = None


def _normalize_review_trigger(value: str | None) -> ReviewTrigger:
    normalized = (value or DEFAULT_REVIEW_TRIGGER).strip().lower()
    if normalized not in {"pr_open", "push"}:
        raise HTTPException(400, "trigger 仅支持 pr_open 或 push")
    return normalized  # type: ignore[return-value]


def _normalize_auto_review_mode(value: str | None) -> AutoReviewMode:
    normalized = (value or "follow_global").strip().lower()
    if normalized not in {"follow_global", "enabled", "disabled"}:
        raise HTTPException(400, "auto_review 仅支持 follow_global/enabled/disabled")
    return normalized  # type: ignore[return-value]


def _resolve_request_user_identity(request: Request | None) -> str:
    if request is None:
        return "local-dev"

    scope_user = request.scope.get("user")
    if scope_user is not None:
        identity = getattr(scope_user, "identity", None) or getattr(
            scope_user, "id", None
        )
        if isinstance(identity, str) and identity.strip():
            return identity.strip()

    for header_name in ("x-user-id", "x-auth-user", "x-user"):
        header_value = request.headers.get(header_name)
        if header_value and header_value.strip():
            return header_value.strip()

    return "local-dev"


def _parse_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _normalize_repository_name(value: str) -> str:
    normalized = value.strip().strip("/")
    if not normalized:
        raise HTTPException(400, "repository 不能为空")
    return normalized


async def _select_profile(user_id: str) -> dict[str, Any]:
    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            result = await session.execute(
                text(PROFILE_SELECT_SQL),
                {"user_id": user_id},
            )
        except SQLAlchemyError as exc:
            raise HTTPException(500, f"查询代码审查全局配置失败: {exc}") from exc

    row = result.mappings().first()
    if not row:
        return {
            "user_id": user_id,
            "auto_review_enabled": DEFAULT_GLOBAL_AUTO_REVIEW_ENABLED,
            "default_trigger": DEFAULT_REVIEW_TRIGGER,
            "updated_at": None,
            "updated_by": None,
        }

    return {
        "user_id": str(row.get("user_id") or user_id),
        "auto_review_enabled": bool(row.get("auto_review_enabled")),
        "default_trigger": _normalize_review_trigger(
            str(row.get("default_trigger") or DEFAULT_REVIEW_TRIGGER)
        ),
        "updated_at": row.get("updated_at"),
        "updated_by": row.get("updated_by"),
    }


async def _upsert_profile(
    *,
    user_id: str,
    auto_review_enabled: bool,
    default_trigger: ReviewTrigger,
    updated_by: str,
) -> None:
    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            await session.execute(
                text(PROFILE_UPSERT_SQL),
                {
                    "user_id": user_id,
                    "auto_review_enabled": auto_review_enabled,
                    "default_trigger": default_trigger,
                    "updated_at": time.time(),
                    "updated_by": updated_by,
                },
            )
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            raise HTTPException(500, f"保存代码审查全局配置失败: {exc}") from exc


async def _list_repo_settings(user_id: str) -> list[dict[str, Any]]:
    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            result = await session.execute(
                text(REPO_SETTING_LIST_SQL),
                {"user_id": user_id},
            )
        except SQLAlchemyError as exc:
            raise HTTPException(500, f"查询仓库审查配置失败: {exc}") from exc

    items: list[dict[str, Any]] = []
    for row in result.mappings().all():
        provider = _normalize_scm_provider(str(row.get("provider") or ""))
        gitlab_base_url = (
            _normalize_gitlab_base_url(str(row.get("gitlab_base_url") or ""))
            if provider == "gitlab"
            else None
        )
        items.append(
            {
                "provider": provider,
                "repository": str(row.get("repository") or "").strip(),
                "gitlab_base_url": gitlab_base_url,
                "auto_review": _normalize_auto_review_mode(
                    str(row.get("auto_review") or "follow_global")
                ),
                "trigger": (
                    _normalize_review_trigger(
                        str(row.get("trigger") or "follow_global").replace(
                            "follow_global", DEFAULT_REVIEW_TRIGGER
                        )
                    )
                    if str(row.get("trigger") or "").strip().lower() != "follow_global"
                    else "follow_global"
                ),
                "updated_at": row.get("updated_at"),
                "updated_by": row.get("updated_by"),
            }
        )
    return items


async def _upsert_repo_setting(
    *,
    user_id: str,
    provider: str,
    repository: str,
    gitlab_base_url: str | None,
    auto_review: AutoReviewMode,
    trigger: ReviewTrigger | Literal["follow_global"],
    updated_by: str,
) -> None:
    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            await session.execute(
                text(REPO_SETTING_UPSERT_SQL),
                {
                    "setting_id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "provider": provider,
                    "gitlab_base_url": gitlab_base_url,
                    "repository": repository,
                    "auto_review": auto_review,
                    "trigger": trigger,
                    "updated_at": time.time(),
                    "updated_by": updated_by,
                },
            )
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            raise HTTPException(500, f"保存仓库审查配置失败: {exc}") from exc


async def _delete_repo_setting(
    *,
    user_id: str,
    provider: str,
    repository: str,
    gitlab_base_url: str | None,
) -> bool:
    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            result = await session.execute(
                text(REPO_SETTING_DELETE_SQL),
                {
                    "user_id": user_id,
                    "provider": provider,
                    "gitlab_base_url": gitlab_base_url,
                    "repository": repository,
                },
            )
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            raise HTTPException(500, f"删除仓库审查配置失败: {exc}") from exc
    return bool(result.rowcount)


def _normalize_profile_payload(payload: dict[str, Any]) -> tuple[bool, ReviewTrigger]:
    auto_review_enabled = _parse_bool(
        payload.get("auto_review_enabled"),
        default=DEFAULT_GLOBAL_AUTO_REVIEW_ENABLED,
    )
    trigger = _normalize_review_trigger(
        str(payload.get("default_trigger") or DEFAULT_REVIEW_TRIGGER)
    )
    return auto_review_enabled, trigger


def _normalize_repo_payload(
    payload: dict[str, Any],
) -> tuple[
    str, str, str | None, AutoReviewMode, ReviewTrigger | Literal["follow_global"]
]:
    provider = _normalize_scm_provider(str(payload.get("provider") or ""))
    repository = _normalize_repository_name(str(payload.get("repository") or ""))
    gitlab_base_url = (
        _normalize_gitlab_base_url(str(payload.get("gitlab_base_url") or ""))
        if provider == "gitlab"
        else None
    )
    auto_review = _normalize_auto_review_mode(str(payload.get("auto_review") or ""))

    raw_trigger = str(payload.get("trigger") or "follow_global").strip().lower()
    if raw_trigger == "follow_global":
        trigger: ReviewTrigger | Literal["follow_global"] = "follow_global"
    else:
        trigger = _normalize_review_trigger(raw_trigger)

    return provider, repository, gitlab_base_url, auto_review, trigger


def _resolve_public_webhook_url(request: Request | None) -> str | None:
    configured = os.getenv("OPENWEBPX_CODE_REVIEW_WEBHOOK_URL", "").strip()
    if configured:
        return configured.rstrip("/")

    base_url = os.getenv("OPENWEBPX_PUBLIC_BASE_URL", "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}{CODE_REVIEW_WEBHOOK_PATH}"

    if request is None:
        return None
    origin = str(request.base_url).rstrip("/")
    if not origin:
        return None
    return f"{origin}{CODE_REVIEW_WEBHOOK_PATH}"


def _resolve_webhook_secret(provider: Literal["github", "gitlab"]) -> str:
    specific_env = (
        "GITHUB_WEBHOOK_SECRET" if provider == "github" else "GITLAB_WEBHOOK_SECRET"
    )
    specific = os.getenv(specific_env, "").strip()
    if specific:
        return specific
    return os.getenv("OPENWEBPX_CODE_REVIEW_WEBHOOK_SECRET", "").strip()


def _resolve_webhook_secret_candidates(
    provider: Literal["github", "gitlab"],
) -> list[str]:
    secrets: list[str] = []
    specific = _resolve_webhook_secret(provider)
    if specific:
        secrets.append(specific)
    generic = os.getenv("OPENWEBPX_CODE_REVIEW_WEBHOOK_SECRET", "").strip()
    if generic and generic not in secrets:
        secrets.append(generic)
    return secrets


def _build_manual_webhook_guide(
    *,
    provider: Literal["github", "gitlab"],
    repository: str,
    webhook_url: str | None,
) -> dict[str, Any]:
    secret = _resolve_webhook_secret(provider)
    if provider == "github":
        return {
            "provider": provider,
            "repository": repository,
            "events": ["push", "pull_request"],
            "payload_url": webhook_url,
            "secret": secret or None,
            "hint": "请在 GitHub 仓库 Settings -> Webhooks 中新增/更新对应 webhook。",
        }
    return {
        "provider": provider,
        "repository": repository,
        "events": ["Push Hook", "Merge Request Hook"],
        "payload_url": webhook_url,
        "secret": secret or None,
        "hint": "请在 GitLab 项目 Settings -> Webhooks 中新增/更新对应 webhook。",
    }


async def _ensure_github_repository_webhook(
    *,
    user_id: str,
    repository: str,
    webhook_url: str,
) -> WebhookSyncResult:
    token = await _resolve_scm_access_token(
        user_id=user_id,
        provider="github",
        gitlab_base_url=None,
        github_auth_mode="github_app",
    )
    secret = _resolve_webhook_secret("github")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    expected_events = {"push", "pull_request"}

    async with httpx.AsyncClient(timeout=20) as http_client:
        hooks_resp = await http_client.get(
            f"https://api.github.com/repos/{repository}/hooks",
            headers=headers,
        )
        if hooks_resp.status_code >= 400:
            raise HTTPException(
                hooks_resp.status_code,
                f"GitHub webhook 列表查询失败: {hooks_resp.text[:200]}",
            )
        hooks_payload = hooks_resp.json() if hooks_resp.content else []
        if not isinstance(hooks_payload, list):
            hooks_payload = []

        matched_hook: dict[str, Any] | None = None
        for item in hooks_payload:
            if not isinstance(item, dict):
                continue
            config = item.get("config") if isinstance(item.get("config"), dict) else {}
            hook_url = str(config.get("url") or "").strip()
            if hook_url == webhook_url:
                matched_hook = item
                break

        update_payload = {
            "active": True,
            "events": sorted(expected_events),
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "insecure_ssl": "0",
            },
        }
        if secret:
            update_payload["config"]["secret"] = secret

        if matched_hook is not None:
            hook_id = matched_hook.get("id")
            if not isinstance(hook_id, int):
                raise HTTPException(502, "GitHub webhook 返回了无效 hook id")
            existing_events = matched_hook.get("events")
            existing_event_set = (
                {str(item).strip() for item in existing_events}
                if isinstance(existing_events, list)
                else set()
            )
            existing_active = bool(matched_hook.get("active"))
            existing_secret = (
                str(
                    (
                        matched_hook.get("config")
                        if isinstance(matched_hook.get("config"), dict)
                        else {}
                    ).get("secret")
                    or ""
                ).strip()
                if secret
                else ""
            )
            if (
                existing_active
                and expected_events.issubset(existing_event_set)
                and (not secret or bool(existing_secret))
            ):
                return WebhookSyncResult(
                    provider="github",
                    repository=repository,
                    enabled=True,
                    ok=True,
                    mode="auto",
                    message="GitHub webhook 已就绪。",
                    webhook_url=webhook_url,
                )
            patch_resp = await http_client.patch(
                f"https://api.github.com/repos/{repository}/hooks/{hook_id}",
                json=update_payload,
                headers=headers,
            )
            if patch_resp.status_code >= 400:
                raise HTTPException(
                    patch_resp.status_code,
                    f"GitHub webhook 更新失败: {patch_resp.text[:200]}",
                )
            return WebhookSyncResult(
                provider="github",
                repository=repository,
                enabled=True,
                ok=True,
                mode="auto",
                message="GitHub webhook 已自动更新。",
                webhook_url=webhook_url,
            )

        create_resp = await http_client.post(
            f"https://api.github.com/repos/{repository}/hooks",
            json=update_payload,
            headers=headers,
        )
        if create_resp.status_code >= 400:
            raise HTTPException(
                create_resp.status_code,
                f"GitHub webhook 创建失败: {create_resp.text[:200]}",
            )
        return WebhookSyncResult(
            provider="github",
            repository=repository,
            enabled=True,
            ok=True,
            mode="auto",
            message="GitHub webhook 已自动创建。",
            webhook_url=webhook_url,
        )


async def _ensure_gitlab_project_webhook(
    *,
    user_id: str,
    repository: str,
    gitlab_base_url: str | None,
    webhook_url: str,
) -> WebhookSyncResult:
    normalized_base_url = _normalize_gitlab_base_url(gitlab_base_url)
    token = await _resolve_scm_access_token(
        user_id=user_id,
        provider="gitlab",
        gitlab_base_url=normalized_base_url,
        github_auth_mode=None,
    )
    secret = _resolve_webhook_secret("gitlab")
    encoded_repo = quote(repository, safe="")
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=20) as http_client:
        project_resp = await http_client.get(
            f"{normalized_base_url}/api/v4/projects/{encoded_repo}",
            headers=headers,
        )
        if project_resp.status_code >= 400:
            raise HTTPException(
                project_resp.status_code,
                f"GitLab 项目查询失败: {project_resp.text[:200]}",
            )
        project_payload = project_resp.json() if project_resp.content else {}
        project_id = (
            project_payload.get("id") if isinstance(project_payload, dict) else None
        )
        if not isinstance(project_id, int):
            raise HTTPException(502, "GitLab 项目查询未返回有效 id")

        hooks_resp = await http_client.get(
            f"{normalized_base_url}/api/v4/projects/{project_id}/hooks",
            headers=headers,
        )
        if hooks_resp.status_code >= 400:
            raise HTTPException(
                hooks_resp.status_code,
                f"GitLab webhook 列表查询失败: {hooks_resp.text[:200]}",
            )
        hooks_payload = hooks_resp.json() if hooks_resp.content else []
        if not isinstance(hooks_payload, list):
            hooks_payload = []

        matched_hook: dict[str, Any] | None = None
        for item in hooks_payload:
            if not isinstance(item, dict):
                continue
            if str(item.get("url") or "").strip() == webhook_url:
                matched_hook = item
                break

        desired_payload: dict[str, Any] = {
            "url": webhook_url,
            "push_events": True,
            "merge_requests_events": True,
            "enable_ssl_verification": True,
        }
        if secret:
            desired_payload["token"] = secret

        if matched_hook is not None:
            hook_id = matched_hook.get("id")
            if not isinstance(hook_id, int):
                raise HTTPException(502, "GitLab webhook 返回了无效 hook id")
            push_enabled = bool(matched_hook.get("push_events"))
            mr_enabled = bool(matched_hook.get("merge_requests_events"))
            if push_enabled and mr_enabled:
                return WebhookSyncResult(
                    provider="gitlab",
                    repository=repository,
                    enabled=True,
                    ok=True,
                    mode="auto",
                    message="GitLab webhook 已就绪。",
                    webhook_url=webhook_url,
                )
            put_resp = await http_client.put(
                f"{normalized_base_url}/api/v4/projects/{project_id}/hooks/{hook_id}",
                data=desired_payload,
                headers=headers,
            )
            if put_resp.status_code >= 400:
                raise HTTPException(
                    put_resp.status_code,
                    f"GitLab webhook 更新失败: {put_resp.text[:200]}",
                )
            return WebhookSyncResult(
                provider="gitlab",
                repository=repository,
                enabled=True,
                ok=True,
                mode="auto",
                message="GitLab webhook 已自动更新。",
                webhook_url=webhook_url,
            )

        create_resp = await http_client.post(
            f"{normalized_base_url}/api/v4/projects/{project_id}/hooks",
            data=desired_payload,
            headers=headers,
        )
        if create_resp.status_code >= 400:
            raise HTTPException(
                create_resp.status_code,
                f"GitLab webhook 创建失败: {create_resp.text[:200]}",
            )
        return WebhookSyncResult(
            provider="gitlab",
            repository=repository,
            enabled=True,
            ok=True,
            mode="auto",
            message="GitLab webhook 已自动创建。",
            webhook_url=webhook_url,
        )


def _is_auto_review_effectively_enabled(
    *,
    auto_review: AutoReviewMode,
    profile: dict[str, Any] | None,
) -> bool:
    if auto_review == "enabled":
        return True
    if auto_review == "disabled":
        return False
    return bool((profile or {}).get("auto_review_enabled"))


async def _sync_repo_webhook_if_needed(
    *,
    user_id: str,
    provider: str,
    repository: str,
    gitlab_base_url: str | None,
    auto_review: AutoReviewMode,
    request: Request,
) -> dict[str, Any]:
    profile = await _select_profile(user_id)
    enabled = _is_auto_review_effectively_enabled(
        auto_review=auto_review,
        profile=profile,
    )
    webhook_url = _resolve_public_webhook_url(request)
    if not enabled:
        return {
            "enabled": False,
            "ok": True,
            "mode": "manual",
            "message": "当前仓库未启用自动审查，未执行 webhook 同步。",
            "provider": provider,
            "repository": repository,
            "webhook_url": webhook_url,
            "manual_setup": _build_manual_webhook_guide(
                provider="github" if provider == "github" else "gitlab",
                repository=repository,
                webhook_url=webhook_url,
            ),
        }

    if not webhook_url:
        return {
            "enabled": True,
            "ok": False,
            "mode": "manual",
            "message": "缺少公开 webhook URL，请配置 OPENWEBPX_CODE_REVIEW_WEBHOOK_URL 或 OPENWEBPX_PUBLIC_BASE_URL。",
            "provider": provider,
            "repository": repository,
            "webhook_url": None,
            "manual_setup": _build_manual_webhook_guide(
                provider="github" if provider == "github" else "gitlab",
                repository=repository,
                webhook_url=None,
            ),
        }

    try:
        if provider == "github":
            result = await _ensure_github_repository_webhook(
                user_id=user_id,
                repository=repository,
                webhook_url=webhook_url,
            )
        else:
            result = await _ensure_gitlab_project_webhook(
                user_id=user_id,
                repository=repository,
                gitlab_base_url=gitlab_base_url,
                webhook_url=webhook_url,
            )
        return {
            "enabled": result.enabled,
            "ok": result.ok,
            "mode": result.mode,
            "message": result.message,
            "provider": result.provider,
            "repository": result.repository,
            "webhook_url": result.webhook_url,
            "manual_setup": _build_manual_webhook_guide(
                provider=result.provider,
                repository=result.repository,
                webhook_url=result.webhook_url,
            ),
        }
    except HTTPException as exc:
        return {
            "enabled": True,
            "ok": False,
            "mode": "manual",
            "message": str(exc.detail),
            "provider": provider,
            "repository": repository,
            "webhook_url": webhook_url,
            "manual_setup": _build_manual_webhook_guide(
                provider="github" if provider == "github" else "gitlab",
                repository=repository,
                webhook_url=webhook_url,
            ),
        }


def _normalize_gitlab_base_url_from_web_url(web_url: str | None) -> str | None:
    if not web_url or not web_url.strip():
        return None

    parsed = urlparse(web_url.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _verify_github_signature(raw_body: bytes, request: Request) -> bool:
    secrets = _resolve_webhook_secret_candidates("github")
    if not secrets:
        return True
    signature = request.headers.get("x-hub-signature-256", "").strip()
    if not signature.startswith("sha256="):
        return False
    actual = signature[7:]
    for secret in secrets:
        expected = hmac_new(secret.encode("utf-8"), raw_body, sha256).hexdigest()
        if compare_digest(actual, expected):
            return True
    return False


def _verify_gitlab_token(request: Request) -> bool:
    secrets = _resolve_webhook_secret_candidates("gitlab")
    if not secrets:
        return True
    provided = request.headers.get("x-gitlab-token", "").strip()
    if not provided:
        return False
    return any(compare_digest(provided, secret) for secret in secrets)


def _verify_custom_webhook_secret(request: Request) -> bool:
    secret = os.getenv("OPENWEBPX_CODE_REVIEW_WEBHOOK_SECRET", "").strip()
    if not secret:
        return True
    provided = request.headers.get("x-openwebpx-webhook-secret", "").strip()
    if not provided:
        return False
    return compare_digest(provided, secret)


def _resolve_webhook_event_context(
    *,
    request: Request,
    payload: dict[str, Any],
) -> WebhookEventContext | None:
    github_event = request.headers.get("x-github-event", "").strip().lower()
    if github_event:
        repository = str(payload.get("repository", {}).get("full_name") or "").strip()
        if not repository:
            return None

        if github_event == "pull_request":
            action = str(payload.get("action") or "").strip().lower()
            if action not in {"opened", "reopened", "synchronize"}:
                return None
            pr = (
                payload.get("pull_request")
                if isinstance(payload.get("pull_request"), dict)
                else {}
            )
            head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
            branch = str(head.get("ref") or "main").strip() or "main"
            pr_number = pr.get("number")
            title = str(pr.get("title") or f"PR #{pr_number}").strip()
            return WebhookEventContext(
                provider="github",
                trigger="pr_open",
                repository=repository,
                branch=branch,
                gitlab_base_url=None,
                title=title,
                event_name=github_event,
                payload=payload,
            )

        if github_event == "push":
            ref = str(payload.get("ref") or "")
            branch = ref.removeprefix("refs/heads/").strip() or "main"
            head_commit = (
                payload.get("head_commit")
                if isinstance(payload.get("head_commit"), dict)
                else {}
            )
            title = str(head_commit.get("message") or f"Push to {branch}").strip()
            return WebhookEventContext(
                provider="github",
                trigger="push",
                repository=repository,
                branch=branch,
                gitlab_base_url=None,
                title=title,
                event_name=github_event,
                payload=payload,
            )
        return None

    gitlab_event = request.headers.get("x-gitlab-event", "").strip().lower()
    if gitlab_event:
        project = (
            payload.get("project") if isinstance(payload.get("project"), dict) else {}
        )
        repository = str(project.get("path_with_namespace") or "").strip()
        gitlab_base_url = _normalize_gitlab_base_url_from_web_url(
            str(project.get("web_url") or "").strip()
        )
        if not repository:
            return None

        if gitlab_event == "merge request hook":
            attributes = (
                payload.get("object_attributes")
                if isinstance(payload.get("object_attributes"), dict)
                else {}
            )
            action = str(attributes.get("action") or "").strip().lower()
            if action not in {"open", "reopen", "update"}:
                return None
            branch = str(attributes.get("source_branch") or "main").strip() or "main"
            title = str(attributes.get("title") or "Merge Request").strip()
            return WebhookEventContext(
                provider="gitlab",
                trigger="pr_open",
                repository=repository,
                branch=branch,
                gitlab_base_url=gitlab_base_url,
                title=title,
                event_name=gitlab_event,
                payload=payload,
            )

        if gitlab_event == "push hook":
            ref = str(payload.get("ref") or "")
            branch = ref.removeprefix("refs/heads/").strip() or "main"
            title = str(payload.get("checkout_sha") or f"Push to {branch}").strip()
            return WebhookEventContext(
                provider="gitlab",
                trigger="push",
                repository=repository,
                branch=branch,
                gitlab_base_url=gitlab_base_url,
                title=title,
                event_name=gitlab_event,
                payload=payload,
            )

    return None


async def _fetch_github_diff_files(
    *,
    http_client: httpx.AsyncClient,
    token: str,
    event: WebhookEventContext,
) -> list[dict[str, Any]]:
    payload = event.payload
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if event.trigger == "pr_open":
        pr = (
            payload.get("pull_request")
            if isinstance(payload.get("pull_request"), dict)
            else {}
        )
        number = pr.get("number")
        if not isinstance(number, int):
            return []
        response = await http_client.get(
            f"https://api.github.com/repos/{event.repository}/pulls/{number}/files",
            params={"per_page": 100},
            headers=headers,
        )
        if response.status_code >= 400:
            raise HTTPException(
                response.status_code,
                f"GitHub PR diff 查询失败: {response.text[:200]}",
            )
        items = response.json() if response.content else []
        if not isinstance(items, list):
            return []
        return [
            {
                "path": item.get("filename"),
                "status": item.get("status"),
                "patch": item.get("patch"),
            }
            for item in items
            if isinstance(item, dict)
        ]

    before = str(payload.get("before") or "").strip()
    after = str(payload.get("after") or "").strip()
    if not before or not after:
        return []

    response = await http_client.get(
        f"https://api.github.com/repos/{event.repository}/compare/{before}...{after}",
        headers=headers,
    )
    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            f"GitHub push diff 查询失败: {response.text[:200]}",
        )
    compare_payload = response.json() if response.content else {}
    files = (
        compare_payload.get("files", []) if isinstance(compare_payload, dict) else []
    )
    if not isinstance(files, list):
        return []
    return [
        {
            "path": item.get("filename"),
            "status": item.get("status"),
            "patch": item.get("patch"),
        }
        for item in files
        if isinstance(item, dict)
    ]


async def _fetch_gitlab_diff_files(
    *,
    http_client: httpx.AsyncClient,
    token: str,
    event: WebhookEventContext,
) -> list[dict[str, Any]]:
    payload = event.payload
    base_url = _normalize_gitlab_base_url(event.gitlab_base_url)
    headers = {"Authorization": f"Bearer {token}"}

    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    project_id = project.get("id")
    if not isinstance(project_id, int):
        return []

    if event.trigger == "pr_open":
        attrs = (
            payload.get("object_attributes")
            if isinstance(payload.get("object_attributes"), dict)
            else {}
        )
        iid = attrs.get("iid")
        if not isinstance(iid, int):
            return []
        response = await http_client.get(
            f"{base_url}/api/v4/projects/{project_id}/merge_requests/{iid}/changes",
            headers=headers,
        )
        if response.status_code >= 400:
            raise HTTPException(
                response.status_code,
                f"GitLab MR diff 查询失败: {response.text[:200]}",
            )
        body = response.json() if response.content else {}
        changes = body.get("changes", []) if isinstance(body, dict) else []
        if not isinstance(changes, list):
            return []
        return [
            {
                "path": item.get("new_path") or item.get("old_path"),
                "status": "modified",
                "patch": item.get("diff"),
            }
            for item in changes
            if isinstance(item, dict)
        ]

    before = str(payload.get("before") or "").strip()
    after = str(payload.get("after") or "").strip()
    if not before or not after:
        commits = (
            payload.get("commits", [])
            if isinstance(payload.get("commits"), list)
            else []
        )
        files: list[dict[str, Any]] = []
        for commit in commits:
            if not isinstance(commit, dict):
                continue
            for key, status in (
                ("added", "added"),
                ("modified", "modified"),
                ("removed", "removed"),
            ):
                raw = commit.get(key)
                if not isinstance(raw, list):
                    continue
                for path in raw:
                    if isinstance(path, str) and path.strip():
                        files.append(
                            {"path": path.strip(), "status": status, "patch": None}
                        )
        return files

    response = await http_client.get(
        f"{base_url}/api/v4/projects/{project_id}/repository/compare",
        params={"from": before, "to": after, "straight": True},
        headers=headers,
    )
    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            f"GitLab push diff 查询失败: {response.text[:200]}",
        )
    body = response.json() if response.content else {}
    diffs = body.get("diffs", []) if isinstance(body, dict) else []
    if not isinstance(diffs, list):
        return []
    return [
        {
            "path": item.get("new_path") or item.get("old_path"),
            "status": "modified",
            "patch": item.get("diff"),
        }
        for item in diffs
        if isinstance(item, dict)
    ]


def _build_diff_excerpt(files: list[dict[str, Any]]) -> str:
    if not files:
        return (
            "未能解析到具体 diff 内容，请至少基于事件上下文执行一次审查并指出风险点。"
        )

    blocks: list[str] = []
    total_chars = 0
    max_chars = 36_000

    for item in files[:40]:
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        status = str(item.get("status") or "modified").strip() or "modified"
        patch = item.get("patch")
        header = f"- {path} ({status})"

        if isinstance(patch, str) and patch.strip():
            trimmed_patch = patch.strip()
            if len(trimmed_patch) > 1800:
                trimmed_patch = f"{trimmed_patch[:1800]}\n... [patch truncated]"
            block = f"{header}\n```diff\n{trimmed_patch}\n```"
        else:
            block = header

        next_total = total_chars + len(block)
        if next_total > max_chars:
            break
        blocks.append(block)
        total_chars = next_total

    return "\n\n".join(blocks) if blocks else "未能解析到具体 diff 内容。"


def _build_review_prompt(
    event: WebhookEventContext, files: list[dict[str, Any]]
) -> str:
    event_label = "PR 事件" if event.trigger == "pr_open" else "Push 事件"
    diff_excerpt = _build_diff_excerpt(files)

    return (
        "请你扮演资深代码审查工程师，对以下变更做一次高质量审查。\n\n"
        "【审查目标】\n"
        "1. 找出功能缺陷、回归风险、并发/性能问题与安全问题。\n"
        "2. 明确指出高风险文件与具体风险原因。\n"
        "3. 给出可执行修复建议（必要时给补丁思路）。\n"
        "4. 如果信息不足，请先说明缺失信息再给结论。\n\n"
        f"【仓库】{event.repository}\n"
        f"【分支】{event.branch}\n"
        f"【事件】{event_label}\n"
        f"【标题】{event.title}\n\n"
        "【变更摘要 / Diff】\n"
        f"{diff_excerpt}\n"
    )


async def _list_matching_repo_rows(
    *,
    provider: str,
    repository: str,
    gitlab_base_url: str | None,
) -> list[dict[str, Any]]:
    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            result = await session.execute(
                text(REPO_SETTING_MATCH_SQL),
                {
                    "provider": provider,
                    "repository": repository,
                    "gitlab_base_url": gitlab_base_url,
                },
            )
        except SQLAlchemyError as exc:
            raise HTTPException(500, f"查询代码审查匹配配置失败: {exc}") from exc
    return [dict(row) for row in result.mappings().all()]


async def _list_global_profiles_by_trigger(
    trigger: ReviewTrigger,
) -> list[dict[str, Any]]:
    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            result = await session.execute(
                text(PROFILE_LIST_BY_TRIGGER_SQL),
                {"default_trigger": trigger},
            )
        except SQLAlchemyError as exc:
            raise HTTPException(500, f"查询代码审查全局配置失败: {exc}") from exc
    return [dict(row) for row in result.mappings().all()]


async def _resolve_webhook_targets(event: WebhookEventContext) -> list[dict[str, Any]]:
    global_profiles = await _list_global_profiles_by_trigger(event.trigger)
    matched_repo_rows = await _list_matching_repo_rows(
        provider=event.provider,
        repository=event.repository,
        gitlab_base_url=event.gitlab_base_url,
    )

    enabled_users: set[str] = {
        str(row.get("user_id") or "").strip()
        for row in global_profiles
        if str(row.get("user_id") or "").strip()
    }

    repo_override_users: set[str] = set()
    for row in matched_repo_rows:
        user_id = str(row.get("user_id") or "").strip()
        if not user_id:
            continue
        repo_override_users.add(user_id)

        auto_review = _normalize_auto_review_mode(str(row.get("auto_review") or ""))
        trigger_raw = str(row.get("trigger") or "follow_global").strip().lower()
        if trigger_raw == "follow_global":
            effective_trigger: ReviewTrigger = event.trigger
            has_matching_global = user_id in enabled_users
        else:
            effective_trigger = _normalize_review_trigger(trigger_raw)
            has_matching_global = True

        if auto_review == "disabled":
            enabled_users.discard(user_id)
            continue

        if auto_review == "follow_global" and not has_matching_global:
            enabled_users.discard(user_id)
            continue

        if effective_trigger == event.trigger:
            enabled_users.add(user_id)
        else:
            enabled_users.discard(user_id)

    targets: list[dict[str, Any]] = []
    for user_id in sorted(enabled_users):
        targets.append(
            {
                "user_id": user_id,
                "provider": event.provider,
                "repository": event.repository,
                "branch": event.branch,
                "gitlab_base_url": event.gitlab_base_url,
            }
        )
    return targets


async def _dispatch_code_review_run(
    *,
    target: dict[str, Any],
    event: WebhookEventContext,
) -> dict[str, Any]:
    user_id = str(target.get("user_id") or "").strip()
    if not user_id:
        return {"ok": False, "reason": "missing_user_id"}

    provider = str(target.get("provider") or event.provider).strip().lower()
    repository = str(target.get("repository") or event.repository).strip()
    branch = str(target.get("branch") or event.branch).strip() or "main"
    gitlab_base_url = (
        _normalize_gitlab_base_url(
            str(target.get("gitlab_base_url") or event.gitlab_base_url or "")
        )
        if provider == "gitlab"
        else None
    )

    token = await _resolve_scm_access_token(
        user_id=user_id,
        provider=provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode="github_app" if provider == "github" else None,
    )

    files: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20) as http_client:
        if provider == "github":
            files = await _fetch_github_diff_files(
                http_client=http_client,
                token=token,
                event=event,
            )
        else:
            files = await _fetch_gitlab_diff_files(
                http_client=http_client,
                token=token,
                event=event,
            )

    prompt = _build_review_prompt(event, files)

    metadata = {
        "name": f"Code Review: {repository} ({event.trigger})",
        "source": "code_review_webhook",
        "repo": repository,
        "branch": branch,
        "provider": provider,
        "graph_id": DEFAULT_REVIEW_GRAPH_ID,
        "github_auth_mode": "github_app" if provider == "github" else None,
        "gitlab_base_url": gitlab_base_url,
        "review_trigger": event.trigger,
        "review_event": event.event_name,
        "review_title": event.title,
        "review_file_count": len(files),
        "review_webhook_at": time.time(),
    }

    session_maker = _get_session_maker()
    thread_id = str(uuid.uuid4())
    async with session_maker() as session:
        thread = ThreadORM(
            thread_id=thread_id,
            user_id=user_id,
            status="idle",
            metadata_json=metadata,
        )
        session.add(thread)
        await session.flush()

        run = await create_run(
            thread_id=thread_id,
            request=RunCreate(
                assistant_id=DEFAULT_REVIEW_GRAPH_ID,
                input={"messages": [{"type": "human", "content": prompt}]},
                config={},
                context={},
                checkpoint=None,
                stream=False,
                stream_mode=["messages-tuple"],
                on_disconnect="continue",
                on_completion=None,
                multitask_strategy=None,
                command=None,
                interrupt_before=None,
                interrupt_after=None,
                stream_subgraphs=False,
                metadata={
                    "source": "code_review_webhook",
                    "event": event.event_name,
                    "trigger": event.trigger,
                    "repository": repository,
                    "branch": branch,
                },
            ),
            user=AuthUser(identity=user_id, is_authenticated=True, permissions=[]),
            session=session,
        )
        await session.commit()

    return {
        "ok": True,
        "user_id": user_id,
        "thread_id": thread_id,
        "run_id": run.run_id,
        "repository": repository,
        "branch": branch,
        "file_count": len(files),
    }


@router.get("/integrations/code-review/settings")
async def get_code_review_settings(request: Request) -> dict[str, Any]:
    user_id = _resolve_request_user_identity(request)
    profile = await _select_profile(user_id)
    repositories = await _list_repo_settings(user_id)
    return {
        "global": {
            "auto_review_enabled": profile["auto_review_enabled"],
            "default_trigger": profile["default_trigger"],
            "updated_at": profile["updated_at"],
            "updated_by": profile["updated_by"],
        },
        "repositories": repositories,
    }


@router.put("/integrations/code-review/settings/global")
async def update_code_review_global_settings(
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    user_id = _resolve_request_user_identity(request)
    auto_review_enabled, default_trigger = _normalize_profile_payload(payload)
    await _upsert_profile(
        user_id=user_id,
        auto_review_enabled=auto_review_enabled,
        default_trigger=default_trigger,
        updated_by=user_id,
    )
    profile = await _select_profile(user_id)
    return {
        "ok": True,
        "global": {
            "auto_review_enabled": profile["auto_review_enabled"],
            "default_trigger": profile["default_trigger"],
            "updated_at": profile["updated_at"],
            "updated_by": profile["updated_by"],
        },
    }


@router.put("/integrations/code-review/settings/repositories")
async def upsert_code_review_repository_setting(
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    user_id = _resolve_request_user_identity(request)
    provider, repository, gitlab_base_url, auto_review, trigger = (
        _normalize_repo_payload(payload)
    )
    await _upsert_repo_setting(
        user_id=user_id,
        provider=provider,
        repository=repository,
        gitlab_base_url=gitlab_base_url,
        auto_review=auto_review,
        trigger=trigger,
        updated_by=user_id,
    )
    webhook_sync = await _sync_repo_webhook_if_needed(
        user_id=user_id,
        provider=provider,
        repository=repository,
        gitlab_base_url=gitlab_base_url,
        auto_review=auto_review,
        request=request,
    )
    repositories = await _list_repo_settings(user_id)
    return {"ok": True, "repositories": repositories, "webhook_sync": webhook_sync}


@router.delete("/integrations/code-review/settings/repositories")
async def delete_code_review_repository_setting(
    provider: str = Query(..., description="github or gitlab"),
    repository: str = Query(..., description="owner/repo"),
    gitlab_base_url: str | None = Query(None),
    request: Request = None,
) -> dict[str, Any]:
    user_id = _resolve_request_user_identity(request)
    normalized_provider = _normalize_scm_provider(provider)
    normalized_repository = _normalize_repository_name(repository)
    normalized_gitlab_base_url = (
        _normalize_gitlab_base_url(gitlab_base_url)
        if normalized_provider == "gitlab"
        else None
    )
    deleted = await _delete_repo_setting(
        user_id=user_id,
        provider=normalized_provider,
        repository=normalized_repository,
        gitlab_base_url=normalized_gitlab_base_url,
    )
    return {
        "ok": True,
        "deleted": deleted,
        "provider": normalized_provider,
        "repository": normalized_repository,
        "gitlab_base_url": normalized_gitlab_base_url,
    }


@public_router.post("/integrations/code-review/webhook")
async def code_review_webhook(request: Request) -> dict[str, Any]:
    raw_body = await request.body()

    if not _verify_custom_webhook_secret(request):
        raise HTTPException(401, "invalid webhook secret")

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "invalid json payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(400, "payload must be object")

    event_context = _resolve_webhook_event_context(request=request, payload=payload)
    if event_context is None:
        return {"ok": True, "accepted": False, "reason": "unsupported_event"}

    if event_context.provider == "github" and not _verify_github_signature(
        raw_body, request
    ):
        raise HTTPException(401, "invalid github signature")
    if event_context.provider == "gitlab" and not _verify_gitlab_token(request):
        raise HTTPException(401, "invalid gitlab token")

    targets = await _resolve_webhook_targets(event_context)
    if not targets:
        return {
            "ok": True,
            "accepted": False,
            "provider": event_context.provider,
            "repository": event_context.repository,
            "trigger": event_context.trigger,
            "reason": "no_enabled_targets",
        }

    results: list[dict[str, Any]] = []
    for target in targets:
        try:
            result = await _dispatch_code_review_run(target=target, event=event_context)
        except HTTPException as exc:
            result = {
                "ok": False,
                "user_id": target.get("user_id"),
                "error": str(exc.detail),
            }
        except Exception as exc:  # pragma: no cover - defensive path
            result = {
                "ok": False,
                "user_id": target.get("user_id"),
                "error": str(exc),
            }
        results.append(result)

    success_count = sum(1 for item in results if item.get("ok") is True)
    return {
        "ok": True,
        "accepted": True,
        "provider": event_context.provider,
        "repository": event_context.repository,
        "trigger": event_context.trigger,
        "target_count": len(targets),
        "success_count": success_count,
        "results": results,
    }
