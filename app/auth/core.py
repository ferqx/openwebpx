from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Literal

import jwt

Role = Literal["admin", "premium", "developer", "reviewer", "free"]
_ALLOWED_ROLES: set[str] = {"admin", "premium", "developer", "reviewer", "free"}
_HASH_SCHEME = "pbkdf2_sha256"
_HASH_ITERATIONS = 260_000

_STORE_LOCK = RLock()
_STORE_LOADED = False
_USERS_BY_ID: dict[str, dict[str, str]] = {}


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


def _build_user_payload(*, identity: str, role: str, team_id: str) -> dict[str, Any]:
    subscription_tier = "premium" if role in {"admin", "premium"} else "free"
    email = f"{identity}@example.com"
    return {
        "identity": identity,
        "display_name": f"User {identity}",
        "is_authenticated": True,
        "permissions": [role, f"{role}:read", f"{role}:write"],
        "role": role,
        "subscription_tier": subscription_tier,
        "team_id": team_id,
        "email": email,
    }


def register_user(
    *,
    username: str,
    password: str,
    role: str | None,
    team_id: str | None,
) -> dict[str, Any]:
    _ensure_store_loaded()

    if len(password) < 6:
        raise ValueError("密码长度至少 6 位")

    identity = normalize_identity(username)
    resolved_role = _resolve_role(role)
    resolved_team_id = _resolve_team_id(team_id, identity=identity)

    with _STORE_LOCK:
        if identity in _USERS_BY_ID:
            raise ValueError("用户名已存在")

        _USERS_BY_ID[identity] = {
            "password_hash": _hash_password(password),
            "role": resolved_role,
            "team_id": resolved_team_id,
            "email": f"{identity}@example.com",
            "display_name": f"User {identity}",
        }
        _persist_store()

    return _build_user_payload(
        identity=identity,
        role=resolved_role,
        team_id=resolved_team_id,
    )


def authenticate_user(*, username: str, password: str) -> dict[str, Any]:
    _ensure_store_loaded()
    identity = normalize_identity(username)

    with _STORE_LOCK:
        stored = _USERS_BY_ID.get(identity)

    if not stored:
        raise ValueError("账号不存在，请先注册")

    if not _verify_password(password, stored["password_hash"]):
        raise ValueError("用户名或密码错误")

    return _build_user_payload(
        identity=identity,
        role=stored["role"],
        team_id=stored["team_id"],
    )


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

    return _build_user_payload(identity=identity, role=role, team_id=team_id)


def reset_auth_state_for_tests() -> None:
    global _STORE_LOADED
    with _STORE_LOCK:
        _USERS_BY_ID.clear()
        _STORE_LOADED = True
        _persist_store()
