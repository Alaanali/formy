import base64

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from core.crypto import DecryptionError, decrypt, encrypt, generate_key

SUB_A = "0199c3f2-1a40-7c31-9e55-00000000aaaa"
SUB_B = "0199c3f2-1a40-7c31-9e55-00000000bbbb"
FIELD_A = "0199c3f2-1a40-7c31-9e55-000000000001"
FIELD_B = "0199c3f2-1a40-7c31-9e55-000000000002"


@pytest.mark.parametrize(
    "value",
    ["4242424242", "", 0, 42, -1.5, True, False, None, ["a", "b"], {"k": "v"}],
)
def test_round_trip_preserves_type(value):
    """JSON-serialised before sealing, so a number comes back a number rather
    than its string form."""
    blob = encrypt(value, submission_id=SUB_A, field_id=FIELD_A)
    assert decrypt(blob, submission_id=SUB_A, field_id=FIELD_A) == value


def test_ciphertext_does_not_contain_the_plaintext():
    blob = encrypt("4242424242", submission_id=SUB_A, field_id=FIELD_A)
    assert "4242424242" not in base64.b64decode(blob).decode(errors="replace")


def test_same_value_encrypts_differently_each_time():
    """A fresh nonce per call. Reuse under one key is a catastrophic break in
    GCM, and identical ciphertexts would also leak which rows match."""
    a = encrypt("same", submission_id=SUB_A, field_id=FIELD_A)
    b = encrypt("same", submission_id=SUB_A, field_id=FIELD_A)
    assert a != b


def test_ciphertext_moved_to_another_field_fails_to_decrypt():
    """The AAD binds a ciphertext to its row, so someone with write access
    cannot copy one answer into another field."""
    blob = encrypt("secret", submission_id=SUB_A, field_id=FIELD_A)
    with pytest.raises(DecryptionError):
        decrypt(blob, submission_id=SUB_A, field_id=FIELD_B)


def test_ciphertext_moved_to_another_submission_fails_to_decrypt():
    blob = encrypt("secret", submission_id=SUB_A, field_id=FIELD_A)
    with pytest.raises(DecryptionError):
        decrypt(blob, submission_id=SUB_B, field_id=FIELD_A)


def test_tampered_ciphertext_is_rejected():
    """GCM is authenticated, so a flipped byte is detected rather than
    decrypting to garbage."""
    blob = encrypt("secret", submission_id=SUB_A, field_id=FIELD_A)
    raw = bytearray(base64.b64decode(blob))
    raw[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        decrypt(base64.b64encode(bytes(raw)).decode(), submission_id=SUB_A, field_id=FIELD_A)


def test_a_different_key_fails_authentication():
    blob = encrypt("secret", submission_id=SUB_A, field_id=FIELD_A)
    with override_settings(FIELD_ENCRYPTION_KEY=generate_key()), pytest.raises(DecryptionError):
        decrypt(blob, submission_id=SUB_A, field_id=FIELD_A)


@pytest.mark.parametrize("bad", ["", base64.b64encode(b"too-short").decode()])
def test_a_missing_or_wrong_length_key_fails_loudly(bad):
    """Refused at use rather than silently encrypting with a weak key."""
    with override_settings(FIELD_ENCRYPTION_KEY=bad), pytest.raises(ImproperlyConfigured):
        encrypt("x", submission_id=SUB_A, field_id=FIELD_A)


def test_generate_key_produces_a_usable_key():
    with override_settings(FIELD_ENCRYPTION_KEY=generate_key()):
        blob = encrypt("x", submission_id=SUB_A, field_id=FIELD_A)
        assert decrypt(blob, submission_id=SUB_A, field_id=FIELD_A) == "x"
