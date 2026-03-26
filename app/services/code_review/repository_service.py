from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_review import (
    RepositoryIntegration,
    RepositoryMembership,
    RepositoryReviewConfig,
)
from app.services.code_review.provider_gitlab import canonicalize_gitlab_instance_url
from app.services.scm import (
    ScmRepositoryService,
    ScmTokenStore,
    _coerce_github_auth_mode,
    _normalize_gitlab_base_url,
    _normalize_scm_provider,
    scm_repository_service,
    scm_token_store,
)

DEFAULT_REVIEW_CONFIG = {
    "review_enabled": False,
    "review_triggers": None,
    "auto_fix_enabled": False,
    "auto_fix_severities": None,
    "auto_fix_requires_approval": True,
    "auto_publish_enabled": False,
}


def _resolve_user_identity(current_user: Any) -> str:
    if isinstance(current_user, str) and current_user.strip():
        return current_user.strip()
    for attr_name in ("identity", "id", "user_id"):
        attr_value = getattr(current_user, attr_name, None)
        if isinstance(attr_value, str) and attr_value.strip():
            return attr_value.strip()
    if isinstance(current_user, dict):
        for key in ("identity", "id", "user_id"):
            value = current_user.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise HTTPException(400, "无法识别当前用户")


def _repo_external_id(repository: dict[str, Any]) -> str:
    external_repo_id = repository.get("id")
    if external_repo_id is None:
        external_repo_id = repository.get("path_with_namespace")
    if external_repo_id is None:
        external_repo_id = repository.get("full_name")
    if external_repo_id is None:
        raise HTTPException(502, "SCM 仓库缺少可同步的外部 ID")
    external_repo_id_str = str(external_repo_id).strip()
    if not external_repo_id_str:
        raise HTTPException(502, "SCM 仓库缺少可同步的外部 ID")
    return external_repo_id_str


def _repo_full_name(repository: dict[str, Any]) -> str | None:
    full_name = repository.get("full_name")
    if isinstance(full_name, str) and full_name.strip():
        return full_name.strip()
    path_with_namespace = repository.get("path_with_namespace")
    if isinstance(path_with_namespace, str) and path_with_namespace.strip():
        return path_with_namespace.strip()
    name = repository.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _integration_identity_key(
    *,
    provider: str,
    external_repo_id: str,
    repository_identity_key: str,
) -> tuple[str, str, str]:
    return provider, external_repo_id, repository_identity_key


def _repository_identity_key_value(
    *,
    provider: str,
    gitlab_base_url: str | None,
) -> str:
    if provider == "gitlab":
        return canonicalize_gitlab_instance_url(gitlab_base_url)
    return ""


class CodeReviewRepositoryService:
    def __init__(
        self,
        *,
        token_store: ScmTokenStore = scm_token_store,
        scm_repository_service: ScmRepositoryService = scm_repository_service,
    ) -> None:
        self.token_store = token_store
        self.scm_repository_service = scm_repository_service

    async def sync_repositories(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
        provider: str,
        gitlab_base_url: str | None = None,
        github_auth_mode: str | None = None,
    ) -> list[dict[str, Any]]:
        user_id = _resolve_user_identity(current_user)
        normalized_provider = _normalize_scm_provider(provider)
        normalized_github_auth_mode = (
            _coerce_github_auth_mode(github_auth_mode)
            if normalized_provider == "github"
            else None
        )
        normalized_gitlab_base_url = (
            _normalize_gitlab_base_url(gitlab_base_url)
            if normalized_provider == "gitlab"
            else None
        )
        repository_identity_key = _repository_identity_key_value(
            provider=normalized_provider,
            gitlab_base_url=normalized_gitlab_base_url,
        )

        token_payload = await self.token_store.resolve_token_payload(
            user_id=user_id,
            provider=normalized_provider,
            gitlab_base_url=normalized_gitlab_base_url,
            github_auth_mode=normalized_github_auth_mode,
        )
        access_token = token_payload["access_token"]
        if normalized_provider == "github":
            repositories = await self.scm_repository_service.list_github_repositories(
                access_token=access_token,
                token_payload=token_payload,
            )
        else:
            repositories = await self.scm_repository_service.list_gitlab_repositories(
                access_token=access_token,
                gitlab_base_url=normalized_gitlab_base_url,
            )
        try:
            synced_integrations = await self._sync_repository_batch(
                session=session,
                current_user=current_user,
                provider=normalized_provider,
                gitlab_base_url=normalized_gitlab_base_url,
                repository_identity_key=repository_identity_key,
                repositories=repositories,
            )
        except IntegrityError:
            await session.rollback()
            synced_integrations = await self._sync_repository_batch(
                session=session,
                current_user=current_user,
                provider=normalized_provider,
                gitlab_base_url=normalized_gitlab_base_url,
                repository_identity_key=repository_identity_key,
                repositories=repositories,
            )
        except SQLAlchemyError as exc:
            await session.rollback()
            raise HTTPException(500, f"同步代码评审仓库失败: {exc}") from exc

        config_by_repository_id = {
            config.repository_integration_id: config
            for config in await self._load_configs(session)
            if config.repository_integration_id is not None
        }
        return [
            self._serialize_repository_summary(
                integration,
                config=config_by_repository_id.get(integration.id),
            )
            for integration in synced_integrations
        ]

    async def list_repositories(
        self,
        *,
        session: AsyncSession,
        _current_user: Any,
    ) -> list[dict[str, Any]]:
        integrations = await self._load_integrations(session)
        integrations.sort(key=lambda item: item.id or 0)
        config_by_repository_id = {
            config.repository_integration_id: config
            for config in await self._load_configs(session)
            if config.repository_integration_id is not None
        }
        return [
            self._serialize_repository_summary(
                integration,
                config=config_by_repository_id.get(integration.id),
            )
            for integration in integrations
        ]

    async def get_repository_config(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
        repository_id: int,
    ) -> dict[str, Any]:
        config = await self._get_visible_config(
            session=session,
            current_user=current_user,
            repository_id=repository_id,
        )
        return self._serialize_config(config)

    async def update_repository_config(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
        repository_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        user_id = _resolve_user_identity(current_user)
        config = await self._get_visible_config(
            session=session,
            current_user=current_user,
            repository_id=repository_id,
        )
        now = datetime.now(UTC)
        updated = False
        for field_name in (
            "review_enabled",
            "review_triggers",
            "auto_fix_enabled",
            "auto_fix_severities",
            "auto_fix_requires_approval",
            "auto_publish_enabled",
        ):
            if field_name in payload:
                setattr(config, field_name, payload[field_name])
                updated = True
        if updated:
            config.updated_by = user_id
            config.updated_at = now

        try:
            await session.commit()
            await session.refresh(config)
        except SQLAlchemyError as exc:
            await session.rollback()
            raise HTTPException(500, f"更新仓库评审配置失败: {exc}") from exc

        return self._serialize_config(config)

    async def _load_integrations(
        self, session: AsyncSession
    ) -> list[RepositoryIntegration]:
        result = await session.scalars(select(RepositoryIntegration))
        return list(result.all())

    async def _load_memberships(
        self, session: AsyncSession
    ) -> list[RepositoryMembership]:
        result = await session.scalars(select(RepositoryMembership))
        return list(result.all())

    async def _load_configs(
        self, session: AsyncSession
    ) -> list[RepositoryReviewConfig]:
        result = await session.scalars(select(RepositoryReviewConfig))
        return list(result.all())

    async def _get_visible_config(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
        repository_id: int,
    ) -> RepositoryReviewConfig:
        user_id = _resolve_user_identity(current_user)
        integrations = await self._load_integrations(session)
        memberships = await self._load_memberships(session)
        visible_ids = {
            membership.repository_integration_id
            for membership in memberships
            if membership.user_id == user_id
            and membership.repository_integration_id is not None
        }
        if repository_id not in visible_ids:
            raise HTTPException(404, "仓库不存在或不可访问")

        configs = await self._load_configs(session)
        for config in configs:
            if config.repository_integration_id == repository_id:
                return config

        integration = next(
            (item for item in integrations if item.id == repository_id),
            None,
        )
        if integration is None:
            raise HTTPException(404, "仓库不存在或不可访问")

        now = datetime.now(UTC)
        try:
            config = await self._ensure_repository_config(
                session=session,
                integration=integration,
                updated_by=user_id,
                now=now,
            )
        except IntegrityError:
            await session.rollback()
            config = await self._ensure_repository_config(
                session=session,
                integration=integration,
                updated_by=user_id,
                now=now,
                retry_existing=True,
            )
        except SQLAlchemyError as exc:
            await session.rollback()
            raise HTTPException(500, f"初始化仓库评审配置失败: {exc}") from exc
        return config

    def _serialize_config(self, config: RepositoryReviewConfig) -> dict[str, Any]:
        return {
            "id": config.id,
            "repository_integration_id": config.repository_integration_id,
            "review_enabled": config.review_enabled,
            "review_triggers": config.review_triggers,
            "auto_fix_enabled": config.auto_fix_enabled,
            "auto_fix_severities": config.auto_fix_severities,
            "auto_fix_requires_approval": config.auto_fix_requires_approval,
            "auto_publish_enabled": config.auto_publish_enabled,
            "updated_by": config.updated_by,
            "updated_at": config.updated_at,
        }

    def _serialize_repository_summary(
        self,
        integration: RepositoryIntegration,
        *,
        config: RepositoryReviewConfig | None = None,
    ) -> dict[str, Any]:
        return {
            "id": integration.id,
            "provider": integration.provider,
            "external_repo_id": integration.external_repo_id,
            "repository_identity_key": integration.repository_identity_key,
            "full_name": integration.full_name,
            "default_branch": integration.default_branch,
            "gitlab_base_url": integration.gitlab_base_url,
            "review_enabled": (
                config.review_enabled
                if config is not None
                else DEFAULT_REVIEW_CONFIG["review_enabled"]
            ),
        }

    async def _sync_repository_batch(
        self,
        *,
        session: AsyncSession,
        current_user: Any,
        provider: str,
        gitlab_base_url: str | None,
        repository_identity_key: str,
        repositories: list[dict[str, Any]],
    ) -> list[RepositoryIntegration]:
        user_id = _resolve_user_identity(current_user)
        now = datetime.now(UTC)
        existing_integrations = await self._load_integrations(session)
        existing_memberships = await self._load_memberships(session)
        existing_configs = await self._load_configs(session)
        integration_by_id: dict[int, RepositoryIntegration] = {
            integration.id: integration
            for integration in existing_integrations
            if integration.id is not None
        }

        integration_by_key: dict[tuple[str, str, str], RepositoryIntegration] = {
            _integration_identity_key(
                provider=integration.provider,
                external_repo_id=integration.external_repo_id,
                repository_identity_key=integration.repository_identity_key,
            ): integration
            for integration in existing_integrations
        }
        membership_keys: set[tuple[str, str, str, str]] = {
            (
                integration.provider,
                integration.external_repo_id,
                integration.repository_identity_key,
                membership.user_id,
            )
            for membership in existing_memberships
            if membership.repository_integration_id is not None
            for integration in [
                integration_by_id.get(membership.repository_integration_id)
            ]
            if integration is not None
        }
        config_keys: set[tuple[str, str, str]] = {
            _integration_identity_key(
                provider=integration.provider,
                external_repo_id=integration.external_repo_id,
                repository_identity_key=integration.repository_identity_key,
            )
            for config in existing_configs
            if config.repository_integration_id is not None
            for integration in [integration_by_id.get(config.repository_integration_id)]
            if integration is not None
        }

        processed_keys: list[tuple[str, str, str]] = []
        staged_integrations: list[RepositoryIntegration] = []
        staged_memberships: list[RepositoryMembership] = []
        staged_configs: list[RepositoryReviewConfig] = []
        current_repo_ids: set[str] = set()

        for repository in repositories:
            external_repo_id = _repo_external_id(repository)
            current_repo_ids.add(external_repo_id)
            integration_key = _integration_identity_key(
                provider=provider,
                external_repo_id=external_repo_id,
                repository_identity_key=repository_identity_key,
            )
            if integration_key in processed_keys:
                continue
            processed_keys.append(integration_key)

            integration = integration_by_key.get(integration_key)
            full_name = _repo_full_name(repository)
            default_branch = repository.get("default_branch")
            default_branch_value = (
                str(default_branch).strip() if isinstance(default_branch, str) else None
            )

            if integration is None:
                integration = RepositoryIntegration(
                    provider=provider,
                    external_repo_id=external_repo_id,
                    repository_identity_key=repository_identity_key,
                    full_name=full_name,
                    default_branch=default_branch_value,
                    gitlab_base_url=gitlab_base_url,
                    webhook_status=None,
                    webhook_management_mode=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(integration)
                integration_by_key[integration_key] = integration
                staged_integrations.append(integration)
            elif integration is not None:
                changed = False
                if full_name is not None and integration.full_name != full_name:
                    integration.full_name = full_name
                    changed = True
                if (
                    default_branch_value is not None
                    and integration.default_branch != default_branch_value
                ):
                    integration.default_branch = default_branch_value
                    changed = True
                if (
                    provider == "gitlab"
                    and integration.gitlab_base_url != gitlab_base_url
                ):
                    integration.gitlab_base_url = gitlab_base_url
                    changed = True
                if integration.repository_identity_key != repository_identity_key:
                    integration.repository_identity_key = repository_identity_key
                    changed = True
                if changed:
                    integration.updated_at = now

            integration = integration_by_key.get(integration_key)
            if integration is None:
                continue

            membership_key = (*integration_key, user_id)
            if membership_key not in membership_keys:
                membership = RepositoryMembership(
                    repository_integration=integration,
                    user_id=user_id,
                    role="owner",  # 标记为 owner
                    can_approve_fixes=True,  # 长期方案：同步者默认拥有审批权
                    created_at=now,
                    updated_at=now,
                )
                session.add(membership)
                membership_keys.add(membership_key)
                staged_memberships.append(membership)

            if integration_key not in config_keys:
                config = RepositoryReviewConfig(
                    repository_integration=integration,
                    updated_by=user_id,
                    updated_at=now,
                    **DEFAULT_REVIEW_CONFIG,
                )
                session.add(config)
                config_keys.add(integration_key)
                staged_configs.append(config)

        existing_in_scope_memberships = [
            membership
            for membership in existing_memberships
            if membership.user_id == user_id
            and membership.repository_integration_id is not None
            and (
                integration := integration_by_id.get(
                    membership.repository_integration_id
                )
            )
            is not None
            and integration.provider == provider
            and integration.repository_identity_key == repository_identity_key
            and integration.external_repo_id not in current_repo_ids
        ]
        for membership in existing_in_scope_memberships:
            await session.delete(membership)

        await session.commit()
        for obj in (*staged_integrations, *staged_memberships, *staged_configs):
            await session.refresh(obj)
        return [
            integration_by_key[key]
            for key in processed_keys
            if key in integration_by_key
        ]

    async def _ensure_repository_config(
        self,
        *,
        session: AsyncSession,
        integration: RepositoryIntegration,
        updated_by: str,
        now: datetime,
        retry_existing: bool = False,
    ) -> RepositoryReviewConfig:
        configs = await self._load_configs(session)
        for config in configs:
            if config.repository_integration_id == integration.id:
                return config

        if retry_existing:
            return await self._create_or_reuse_repository_config(
                session=session,
                integration=integration,
                updated_by=updated_by,
                now=now,
                retry_existing=True,
            )
        return await self._create_or_reuse_repository_config(
            session=session,
            integration=integration,
            updated_by=updated_by,
            now=now,
            retry_existing=False,
        )

    async def _create_or_reuse_repository_config(
        self,
        *,
        session: AsyncSession,
        integration: RepositoryIntegration,
        updated_by: str,
        now: datetime,
        retry_existing: bool,
    ) -> RepositoryReviewConfig:
        config = RepositoryReviewConfig(
            repository_integration=integration,
            updated_by=updated_by,
            updated_at=now,
            **DEFAULT_REVIEW_CONFIG,
        )
        if not retry_existing:
            session.add(config)
        else:
            configs = await self._load_configs(session)
            for existing in configs:
                if existing.repository_integration_id == integration.id:
                    return existing
            session.add(config)
        await session.commit()
        await session.refresh(config)
        return config


code_review_repository_service = CodeReviewRepositoryService()
