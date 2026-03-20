from __future__ import annotations

from typing import Literal, TypedDict

ScmProvider = Literal["github", "gitlab"]
ScmGithubAuthMode = Literal["github_app"]


class TokenPayload(TypedDict, total=False):
    """令牌载荷结构."""

    provider: str
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    expires_at: float | None
    updated_at: float
    # GitHub specific
    github_token_source: str | None
    github_auth_mode: str | None
    # GitLab specific
    gitlab_base_url: str | None
    # User profile
    scm_user_login: str
    scm_user_name: str
    scm_user_email: str
    # OAuth response fields
    scope: str | None
    token_type: str | None
    refresh_token_expires_in: int | None


class ScmConnectionInfo(TypedDict):
    """SCM 连接信息输出."""

    cache_key: str
    provider: str
    github_auth_mode: str | None
    gitlab_base_url: str | None
    is_enterprise: bool
    connection_key: str
    updated_at: float | None
    expires_at: float | None
    expired: bool
    has_refresh_token: bool
