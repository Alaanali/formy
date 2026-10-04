from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

NONCE_BYTES = 12
KEY_BYTES = 32


class DecryptionError(Exception):
    """Ciphertext failed authentication."""


def _key() -> bytes:
    key = base64.b64decode(getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "")
    if len(key) != KEY_BYTES:
        raise ImproperlyConfigured(
            f"FIELD_ENCRYPTION_KEY must be {KEY_BYTES} base64-encoded bytes."
        )
    return key


def _aad(submission_id: str, field_id: str) -> bytes:
    """Binds a ciphertext to the row that owns it."""
    return f"{submission_id}:{field_id}".encode()


def encrypt(value: Any, *, submission_id: str, field_id: str) -> str:
    """Base64 ciphertext. JSON-serialised first, so types survive the trip.

    Two details matter more than the choice of AES-256-GCM. The nonce is
    random per call: reuse under one key is a catastrophic break in GCM, not
    a weakness. And the AAD binds the ciphertext to its row, so one copied
    between answers fails to decrypt rather than landing in the wrong
    submission.
    """
    nonce = os.urandom(NONCE_BYTES)
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    sealed = AESGCM(_key()).encrypt(nonce, payload, _aad(str(submission_id), str(field_id)))
    return base64.b64encode(nonce + sealed).decode()


def decrypt(blob: str, *, submission_id: str, field_id: str) -> Any:
    raw = base64.b64decode(blob)
    nonce, sealed = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
    try:
        payload = AESGCM(_key()).decrypt(nonce, sealed, _aad(str(submission_id), str(field_id)))
    except InvalidTag as exc:
        raise DecryptionError(
            "Ciphertext failed authentication: wrong key, or it does not belong "
            "to this submission and field."
        ) from exc
    return json.loads(payload)


def generate_key() -> str:
    """Base64 key for FIELD_ENCRYPTION_KEY."""
    return base64.b64encode(os.urandom(KEY_BYTES)).decode()
