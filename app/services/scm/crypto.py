from __future__ import annotations

import json
import os
from base64 import urlsafe_b64encode
from binascii import Error as BinasciiError
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet, InvalidToken

if TYPE_CHECKING:
    from .types import TokenPayload


def _build_scm_token_cipher() -> Fernet:
    jwt_secret = (
        os.getenv("AUTH_JWT_SECRET", "").strip()
        or "sandbox-agent-dev-secret-change-me-please-use-env-in-production"
    )
    derived = sha256(f"sandbox-agent-scm-token::{jwt_secret}".encode()).digest()
    return Fernet(urlsafe_b64encode(derived))


def _build_scm_state_signing_key() -> bytes:
    jwt_secret = (
        os.getenv("AUTH_JWT_SECRET", "").strip()
        or "sandbox-agent-dev-secret-change-me-please-use-env-in-production"
    )
    return sha256(f"sandbox-agent-scm-state::{jwt_secret}".encode()).digest()


def _b64url_encode(data: bytes) -> str:
    return urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    from base64 import urlsafe_b64decode

    return urlsafe_b64decode(f"{data}{padding}".encode())


def _encode_scm_oauth_state_token(payload: dict[str, Any]) -> str:
    raw_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    payload_part = _b64url_encode(raw_payload)
    signature = hmac_new(
        SCM_STATE_SIGNING_KEY,
        payload_part.encode("utf-8"),
        sha256,
    ).digest()
    signature_part = _b64url_encode(signature)
    return f"{payload_part}.{signature_part}"


def _decode_scm_oauth_state_token(state: str) -> dict[str, Any] | None:
    payload_part, sep, signature_part = state.partition(".")
    if not sep or not payload_part or not signature_part:
        return None
    expected_signature = hmac_new(
        SCM_STATE_SIGNING_KEY,
        payload_part.encode("utf-8"),
        sha256,
    ).digest()
    try:
        signature = _b64url_decode(signature_part)
    except (ValueError, BinasciiError):
        return None
    if not compare_digest(signature, expected_signature):
        return None
    try:
        raw_payload = _b64url_decode(payload_part)
        parsed = json.loads(raw_payload.decode("utf-8"))
    except (ValueError, BinasciiError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _encrypt_scm_token_payload(payload: TokenPayload) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return SCM_TOKEN_CIPHER.encrypt(raw).decode("utf-8")


def _decrypt_scm_token_payload(token_encrypted: str) -> dict[str, Any] | None:
    try:
        raw = SCM_TOKEN_CIPHER.decrypt(token_encrypted.encode("utf-8"))
    except InvalidToken:
        return None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


# Global instances
SCM_TOKEN_CIPHER = _build_scm_token_cipher()
SCM_STATE_SIGNING_KEY = _build_scm_state_signing_key()
