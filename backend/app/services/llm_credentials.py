"""Fail-closed credential encryption and fixed provider key resolution."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.models.enums import LLMCredentialSource, LLMProvider

ENVELOPE_VERSION = 1
MAX_KEY_LENGTH = 4096
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class CredentialError(ValueError):
    """Safe credential configuration/decryption failure."""


def _decode_key(value: str) -> bytes:
    raw = value.strip()
    if not raw:
        raise CredentialError("credential keyring is empty")
    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as exc:
        raise CredentialError("credential keyring value is invalid") from exc
    if len(decoded) != 32:
        raise CredentialError("credential keyring values must be 256-bit")
    return decoded


def parse_keyring(raw: str | Mapping[str, str], active_key_id: str) -> dict[str, bytes]:
    try:
        values = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError) as exc:
        raise CredentialError("credential keyring is invalid") from exc
    if (
        not isinstance(values, dict)
        or not values
        or not _KEY_ID.fullmatch(active_key_id)
    ):
        raise CredentialError("credential keyring configuration is invalid")
    result = {str(key): _decode_key(str(value)) for key, value in values.items()}
    if active_key_id not in result:
        raise CredentialError("active credential key is unavailable")
    return result


def validate_plaintext_key(value: str, *, max_length: int = MAX_KEY_LENGTH) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise CredentialError("credential key is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise CredentialError("credential key is invalid")
    return value


def credential_fingerprint(value: str) -> str:
    return hashlib.sha256(validate_plaintext_key(value).encode()).hexdigest()


def masked_hint(value: str) -> str:
    value = validate_plaintext_key(value)
    return "••••" if len(value) <= 4 else f"••••{value[-4:]}"


def _aad(row_id: uuid.UUID, provider: LLMProvider) -> bytes:
    return json.dumps(
        {
            "version": ENVELOPE_VERSION,
            "credential_id": str(row_id),
            "provider": provider.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def encrypt_credential(
    plaintext: str,
    *,
    credential_id: uuid.UUID,
    provider: LLMProvider,
    keyring: Mapping[str, bytes],
    active_key_id: str,
) -> tuple[bytes, str, str, str]:
    plaintext = validate_plaintext_key(plaintext)
    key = keyring.get(active_key_id)
    if key is None or len(key) != 32:
        raise CredentialError("active credential key is unavailable")
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(
        nonce, plaintext.encode(), _aad(credential_id, provider)
    )
    envelope = bytes([ENVELOPE_VERSION, len(nonce)]) + nonce + ciphertext
    return (
        envelope,
        active_key_id,
        masked_hint(plaintext),
        credential_fingerprint(plaintext),
    )


def decrypt_credential(
    envelope: bytes,
    *,
    credential_id: uuid.UUID,
    provider: LLMProvider,
    keyring: Mapping[str, bytes],
    key_id: str,
) -> str:
    if not isinstance(envelope, bytes) or len(envelope) < 15 or key_id not in keyring:
        raise CredentialError("credential cannot be decrypted")
    if envelope[0] != ENVELOPE_VERSION or envelope[1] != 12:
        raise CredentialError("credential envelope is invalid")
    key = keyring[key_id]
    if len(key) != 32:
        raise CredentialError("credential key is invalid")
    try:
        value = (
            AESGCM(key)
            .decrypt(envelope[2:14], envelope[14:], _aad(credential_id, provider))
            .decode("utf-8")
        )
        return validate_plaintext_key(value)
    except Exception as exc:
        raise CredentialError("credential cannot be decrypted") from exc


_PROVIDER_ENV: dict[LLMProvider, tuple[str, ...]] = {
    LLMProvider.OPENAI: ("OPENAI_API_KEY",),
    LLMProvider.ANTHROPIC: ("ANTHROPIC_API_KEY",),
    LLMProvider.GEMINI: ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    LLMProvider.DEEPSEEK: ("DEEPSEEK_API_KEY",),
    LLMProvider.OPENCODE_ZEN: ("OPENCODE_API_KEY",),
    LLMProvider.BEDROCK: (),
}


def supported_environment_keys(provider: LLMProvider) -> tuple[str, ...]:
    return _PROVIDER_ENV[provider]


def resolve_environment_key(
    provider: LLMProvider,
    environment_key_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    if provider is LLMProvider.BEDROCK:
        return None
    allowed = _PROVIDER_ENV[provider]
    if environment_key_name is not None and environment_key_name not in allowed:
        raise CredentialError("environment credential is invalid")
    environ = os.environ if environ is None else environ
    name = environment_key_name or allowed[0]
    value = environ.get(name)
    return validate_plaintext_key(value) if value else None


@dataclass(frozen=True)
class CredentialMaterial:
    source: LLMCredentialSource
    value: str | None


def resolve_credential(
    provider: LLMProvider,
    source: LLMCredentialSource,
    *,
    environment: Mapping[str, str] | None = None,
    environment_key_name: str | None = None,
    ciphertext: bytes | None = None,
    credential_id: uuid.UUID | None = None,
    keyring: Mapping[str, bytes] | None = None,
    key_id: str | None = None,
) -> CredentialMaterial:
    if source is LLMCredentialSource.ENVIRONMENT:
        return CredentialMaterial(
            source,
            resolve_environment_key(provider, environment_key_name, environment),
        )
    if source is LLMCredentialSource.STORED:
        if not ciphertext or credential_id is None or not keyring or not key_id:
            raise CredentialError("stored credential unavailable")
        return CredentialMaterial(
            source,
            decrypt_credential(
                ciphertext,
                credential_id=credential_id,
                provider=provider,
                keyring=keyring,
                key_id=key_id,
            ),
        )
    return CredentialMaterial(LLMCredentialSource.NONE, None)
