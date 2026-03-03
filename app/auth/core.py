from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Literal

import jwt
from aegra_api.core.orm import _get_session_maker
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

Role = Literal["admin", "premium", "developer", "reviewer", "free"]
_ALLOWED_ROLES: set[str] = {"admin", "premium", "developer", "reviewer", "free"}
_HASH_SCHEME = "pbkdf2_sha256"
_HASH_ITERATIONS = 260_000

_STORE_LOCK = RLock()
_STORE_LOADED = False
_USERS_BY_ID: dict[str, dict[str, str]] = {}

AUTH_USER_INSERT_SQL = """
INSERT INTO auth_users
(
  identity,
  password_hash,
  auth_source,
  role,
  team_id,
  display_name,
  email,
  created_at,
  updated_at
)
VALUES
(
  :identity,
  :password_hash,
  :auth_source,
  :role,
  :team_id,
  :display_name,
  :email,
  :created_at,
  :updated_at
)
"""

AUTH_USER_UPSERT_SQL = """
INSERT INTO auth_users
(
  identity,
  password_hash,
  auth_source,
  role,
  team_id,
  display_name,
  email,
  created_at,
  updated_at
)
VALUES
(
  :identity,
  :password_hash,
  :auth_source,
  :role,
  :team_id,
  :display_name,
  :email,
  :created_at,
  :updated_at
)
ON CONFLICT (identity) DO UPDATE
SET
  password_hash = COALESCE(EXCLUDED.password_hash, auth_users.password_hash),
  auth_source = EXCLUDED.auth_source,
  role = EXCLUDED.role,
  team_id = EXCLUDED.team_id,
  display_name = EXCLUDED.display_name,
  email = EXCLUDED.email,
  updated_at = EXCLUDED.updated_at
"""

AUTH_USER_SELECT_SQL = """
SELECT
  identity,
  password_hash,
  auth_source,
  role,
  team_id,
  display_name,
  email
FROM auth_users
WHERE identity = :identity
LIMIT 1
"""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _users_file_path() -> Path:
    raw = os.getenv("AUTH_USERS_FILE", "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.is_absolute():
            return path
        return (_project_root() / path).resolve()
    return (_project_root() / "data" / "auth_users.json").resolve()


def _ensure_store_loaded() -> None:
    global _STORE_LOADED
    with _STORE_LOCK:
        if _STORE_LOADED:
            return
        path = _users_file_path()
        if not path.exists():
            _STORE_LOADED = True
            return

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}

        if isinstance(payload, dict):
            for identity, record in payload.items():
                if not isinstance(identity, str) or not isinstance(record, dict):
                    continue
                password_hash = record.get("password_hash")
                role = record.get("role")
                team_id = record.get("team_id")
                email = record.get("email")
                display_name = record.get("display_name")
                if not isinstance(password_hash, str):
                    continue
                if not isinstance(role, str):
                    continue
                if not isinstance(team_id, str):
                    continue
                if not isinstance(email, str):
                    continue
                if not isinstance(display_name, str):
                    continue
                _USERS_BY_ID[identity] = {
                    "password_hash": password_hash,
                    "role": role,
                    "team_id": team_id,
                    "email": email,
                    "display_name": display_name,
                }

        _STORE_LOADED = True


def _persist_store() -> None:
    path = _users_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_USERS_BY_ID, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _db_auth_enabled() -> bool:
    return _env_flag("AUTH_DB_ENABLED", default=True)


def _file_fallback_enabled() -> bool:
    return _env_flag("AUTH_FILE_FALLBACK_ENABLED", default=True)


def _ldap_enabled() -> bool:
    return _env_flag("AUTH_LDAP_ENABLED", default=False)


def normalize_identity(raw_value: str, *, fallback: str = "user") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", raw_value.strip())
    compact = re.sub(r"_+", "_", normalized).strip("_").lower()
    return compact or fallback


def _resolve_role(role: str | None) -> str:
    if isinstance(role, str):
        lowered = role.strip().lower()
        if lowered in _ALLOWED_ROLES:
            return lowered
    env_default = os.getenv("AUTH_DEFAULT_ROLE", "developer").strip().lower()
    if env_default in _ALLOWED_ROLES:
        return env_default
    return "developer"


def _resolve_team_id(team_id: str | None, *, identity: str) -> str:
    if isinstance(team_id, str) and team_id.strip():
        return normalize_identity(team_id, fallback=identity)
    env_default = os.getenv("AUTH_DEFAULT_TEAM_ID", "").strip()
    if env_default:
        return normalize_identity(env_default, fallback=identity)
    # 默认按用户隔离，避免不同账号共享同一团队看到相同线程
    return identity


def _resolve_email(email: str | None, *, identity: str) -> str:
    if isinstance(email, str) and email.strip():
        return email.strip().lower()
    return f"{identity}@example.com"


def _resolve_display_name(display_name: str | None, *, identity: str) -> str:
    if isinstance(display_name, str) and display_name.strip():
        return display_name.strip()
    return f"User {identity}"


def _hash_password(password: str, *, salt: str | None = None) -> str:
    actual_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        actual_salt.encode("utf-8"),
        _HASH_ITERATIONS,
    ).hex()
    return f"{_HASH_SCHEME}${_HASH_ITERATIONS}${actual_salt}${digest}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iteration_raw, salt, digest = stored_hash.split("$", 3)
    except ValueError:
        return False
    if scheme != _HASH_SCHEME:
        return False
    try:
        iterations = int(iteration_raw)
    except ValueError:
        return False

    calculated = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(calculated, digest)


def _build_user_payload(
    *,
    identity: str,
    role: str,
    team_id: str,
    display_name: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    subscription_tier = "premium" if role in {"admin", "premium"} else "free"
    resolved_display_name = _resolve_display_name(display_name, identity=identity)
    resolved_email = _resolve_email(email, identity=identity)
    return {
        "identity": identity,
        "display_name": resolved_display_name,
        "is_authenticated": True,
        "permissions": [role, f"{role}:read", f"{role}:write"],
        "role": role,
        "subscription_tier": subscription_tier,
        "team_id": team_id,
        "email": resolved_email,
    }


def _build_user_record(
    *,
    identity: str,
    password_hash: str | None,
    auth_source: str,
    role: str,
    team_id: str,
    display_name: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    return {
        "identity": identity,
        "password_hash": password_hash,
        "auth_source": auth_source,
        "role": role,
        "team_id": team_id,
        "display_name": _resolve_display_name(display_name, identity=identity),
        "email": _resolve_email(email, identity=identity),
    }


def _file_get_user(identity: str) -> dict[str, str] | None:
    _ensure_store_loaded()
    with _STORE_LOCK:
        stored = _USERS_BY_ID.get(identity)
        if not stored:
            return None
        return dict(stored)


def _file_register_user(
    *, identity: str, password_hash: str, role: str, team_id: str
) -> dict[str, Any]:
    _ensure_store_loaded()
    with _STORE_LOCK:
        if identity in _USERS_BY_ID:
            raise ValueError("用户名已存在")

        _USERS_BY_ID[identity] = {
            "password_hash": password_hash,
            "role": role,
            "team_id": team_id,
            "email": f"{identity}@example.com",
            "display_name": f"User {identity}",
        }
        _persist_store()

    return _build_user_payload(
        identity=identity,
        role=role,
        team_id=team_id,
    )


def _file_authenticate_user(
    *, identity: str, password: str
) -> tuple[dict[str, Any], bool]:
    stored = _file_get_user(identity)
    if not stored:
        return {}, False
    if not _verify_password(password, stored["password_hash"]):
        return {}, True
    return (
        _build_user_payload(
            identity=identity,
            role=stored["role"],
            team_id=stored["team_id"],
            display_name=stored.get("display_name"),
            email=stored.get("email"),
        ),
        False,
    )


def _db_row_to_user_record(row: Any) -> dict[str, Any]:
    return _build_user_record(
        identity=str(row.get("identity") or ""),
        password_hash=(
            str(row.get("password_hash"))
            if isinstance(row.get("password_hash"), str)
            else None
        ),
        auth_source=str(row.get("auth_source") or "local"),
        role=_resolve_role(str(row.get("role") or "developer")),
        team_id=_resolve_team_id(
            str(row.get("team_id") or ""),
            identity=str(row.get("identity") or ""),
        ),
        display_name=(
            str(row.get("display_name"))
            if isinstance(row.get("display_name"), str)
            else None
        ),
        email=str(row.get("email")) if isinstance(row.get("email"), str) else None,
    )


def _record_to_user_payload(record: dict[str, Any]) -> dict[str, Any]:
    return _build_user_payload(
        identity=str(record["identity"]),
        role=_resolve_role(str(record.get("role"))),
        team_id=_resolve_team_id(
            str(record.get("team_id") or ""),
            identity=str(record["identity"]),
        ),
        display_name=(
            str(record.get("display_name"))
            if isinstance(record.get("display_name"), str)
            else None
        ),
        email=str(record.get("email"))
        if isinstance(record.get("email"), str)
        else None,
    )


async def _fetch_db_user(identity: str) -> dict[str, Any] | None:
    session_maker = _get_session_maker()
    async with session_maker() as session:
        result = await session.execute(
            text(AUTH_USER_SELECT_SQL),
            {"identity": identity},
        )

    row = result.mappings().first()
    if not row:
        return None
    return _db_row_to_user_record(row)


async def _insert_db_user(record: dict[str, Any]) -> None:
    session_maker = _get_session_maker()
    now = time.time()
    async with session_maker() as session:
        try:
            await session.execute(
                text(AUTH_USER_INSERT_SQL),
                {
                    **record,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise


async def _upsert_db_user(record: dict[str, Any]) -> None:
    session_maker = _get_session_maker()
    now = time.time()
    async with session_maker() as session:
        try:
            await session.execute(
                text(AUTH_USER_UPSERT_SQL),
                {
                    **record,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise


def _ldap_bind_dn_for_username(username: str) -> str:
    template = os.getenv("AUTH_LDAP_BIND_DN_TEMPLATE", "").strip()
    if not template:
        raise ValueError("LDAP 未配置 AUTH_LDAP_BIND_DN_TEMPLATE")
    try:
        return template.format(username=username.strip())
    except KeyError as exc:
        raise ValueError("AUTH_LDAP_BIND_DN_TEMPLATE 仅支持 {username} 占位符") from exc


def _ldap_profile_for_username(username: str) -> dict[str, Any]:
    identity = normalize_identity(username)
    role = _resolve_role(os.getenv("AUTH_LDAP_DEFAULT_ROLE"))
    team_id = _resolve_team_id(
        os.getenv("AUTH_LDAP_DEFAULT_TEAM_ID"), identity=identity
    )
    email = _resolve_email(None, identity=identity)
    display_name = _resolve_display_name(username, identity=identity)
    return _build_user_record(
        identity=identity,
        password_hash=None,
        auth_source="ldap",
        role=role,
        team_id=team_id,
        display_name=display_name,
        email=email,
    )


def _authenticate_user_via_ldap_sync(*, username: str, password: str) -> dict[str, Any]:
    if not password:
        raise ValueError("用户名或密码错误")

    ldap_server_uri = os.getenv("AUTH_LDAP_SERVER_URI", "").strip()
    if not ldap_server_uri:
        raise ValueError("LDAP 未配置 AUTH_LDAP_SERVER_URI")

    try:
        from ldap3 import Connection, Server
        from ldap3.core.exceptions import LDAPException, LDAPInvalidCredentialsResult
    except ImportError as exc:
        raise ValueError("LDAP 登录已启用，但未安装 ldap3 依赖") from exc

    bind_dn = _ldap_bind_dn_for_username(username)
    try:
        conn = Connection(
            Server(ldap_server_uri),
            user=bind_dn,
            password=password,
            auto_bind=True,
            raise_exceptions=True,
        )
    except LDAPInvalidCredentialsResult as exc:
        raise ValueError("用户名或密码错误") from exc
    except LDAPException as exc:
        raise ValueError(f"LDAP 登录失败: {exc}") from exc

    try:
        return _ldap_profile_for_username(username)
    finally:
        conn.unbind()


async def _authenticate_user_via_ldap(
    *, username: str, password: str
) -> dict[str, Any] | None:
    if not _ldap_enabled():
        return None
    return await asyncio.to_thread(
        _authenticate_user_via_ldap_sync,
        username=username,
        password=password,
    )


async def register_user(
    *,
    username: str,
    password: str,
    role: str | None,
    team_id: str | None,
) -> dict[str, Any]:
    if len(password) < 6:
        raise ValueError("密码长度至少 6 位")

    identity = normalize_identity(username)
    resolved_role = _resolve_role(role)
    resolved_team_id = _resolve_team_id(team_id, identity=identity)
    password_hash = _hash_password(password)
    user_record = _build_user_record(
        identity=identity,
        password_hash=password_hash,
        auth_source="local",
        role=resolved_role,
        team_id=resolved_team_id,
    )

    if _db_auth_enabled():
        try:
            await _insert_db_user(user_record)
            return _record_to_user_payload(user_record)
        except IntegrityError as exc:
            raise ValueError("用户名已存在") from exc
        except (SQLAlchemyError, RuntimeError) as exc:
            if not _file_fallback_enabled():
                raise ValueError("用户数据库不可用，请稍后重试") from exc

    return _file_register_user(
        identity=identity,
        password_hash=password_hash,
        role=resolved_role,
        team_id=resolved_team_id,
    )


async def authenticate_user(*, username: str, password: str) -> dict[str, Any]:
    identity = normalize_identity(username)
    saw_local_user = False

    if _db_auth_enabled():
        try:
            stored = await _fetch_db_user(identity)
        except (SQLAlchemyError, RuntimeError) as exc:
            if not _file_fallback_enabled():
                raise ValueError("用户数据库不可用，请稍后重试") from exc
            stored = None
        if stored:
            password_hash = stored.get("password_hash")
            if isinstance(password_hash, str) and _verify_password(
                password, password_hash
            ):
                return _record_to_user_payload(stored)
            if isinstance(password_hash, str):
                saw_local_user = True

    file_user_payload, file_user_exists = _file_authenticate_user(
        identity=identity, password=password
    )
    if file_user_payload:
        if _db_auth_enabled():
            file_record = _file_get_user(identity)
            if file_record:
                mirrored_record = _build_user_record(
                    identity=identity,
                    password_hash=file_record["password_hash"],
                    auth_source="local",
                    role=file_record["role"],
                    team_id=file_record["team_id"],
                    display_name=file_record.get("display_name"),
                    email=file_record.get("email"),
                )
                with contextlib.suppress(SQLAlchemyError, RuntimeError):
                    await _upsert_db_user(mirrored_record)
        return file_user_payload
    saw_local_user = saw_local_user or file_user_exists

    ldap_record = await _authenticate_user_via_ldap(
        username=username,
        password=password,
    )
    if ldap_record:
        if _db_auth_enabled():
            try:
                await _upsert_db_user(ldap_record)
            except (SQLAlchemyError, RuntimeError) as exc:
                if not _file_fallback_enabled():
                    raise ValueError("用户数据库不可用，请稍后重试") from exc
        return _record_to_user_payload(ldap_record)

    if saw_local_user:
        raise ValueError("用户名或密码错误")
    raise ValueError("账号不存在，请先注册")


def _jwt_secret() -> str:
    secret = os.getenv("AUTH_JWT_SECRET", "").strip()
    if secret:
        return secret
    # 本地开发默认值，生产环境请务必设置 AUTH_JWT_SECRET
    return "openwebpx-dev-secret-change-me-please-use-env-in-production"


def _jwt_algorithm() -> str:
    value = os.getenv("AUTH_JWT_ALGORITHM", "HS256").strip()
    return value or "HS256"


def _token_expire_minutes() -> int:
    raw = os.getenv("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES", "1440").strip()
    try:
        value = int(raw)
    except ValueError:
        return 1440
    return value if value > 0 else 1440


def create_access_token(user: dict[str, Any]) -> str:
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=_token_expire_minutes())

    payload = {
        "sub": str(user["identity"]),
        "role": str(user.get("role") or "developer"),
        "team_id": str(user.get("team_id") or user["identity"]),
        "display_name": str(user.get("display_name") or user["identity"]),
        "email": str(user.get("email") or f"{user['identity']}@example.com"),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }

    return jwt.encode(payload, _jwt_secret(), algorithm=_jwt_algorithm())


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[_jwt_algorithm()],
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("令牌已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError("无效令牌") from exc

    identity_raw = payload.get("sub")
    if not isinstance(identity_raw, str) or not identity_raw.strip():
        raise ValueError("令牌缺少用户标识")

    identity = normalize_identity(identity_raw)
    role = _resolve_role(
        payload.get("role") if isinstance(payload.get("role"), str) else None
    )
    team_id_raw = payload.get("team_id")
    team_id = (
        normalize_identity(team_id_raw, fallback=identity)
        if isinstance(team_id_raw, str)
        else identity
    )

    return _build_user_payload(
        identity=identity,
        role=role,
        team_id=team_id,
        display_name=(
            str(payload.get("display_name"))
            if isinstance(payload.get("display_name"), str)
            else None
        ),
        email=str(payload.get("email"))
        if isinstance(payload.get("email"), str)
        else None,
    )


def reset_auth_state_for_tests() -> None:
    global _STORE_LOADED
    with _STORE_LOCK:
        _USERS_BY_ID.clear()
        _STORE_LOADED = True
        _persist_store()
