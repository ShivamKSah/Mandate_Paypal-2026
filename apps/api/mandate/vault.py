"""Fernet encryption and masking for stored PayPal vault tokens."""
import os

from cryptography.fernet import Fernet, InvalidToken


class VaultConfigError(RuntimeError):
    """Raised when VAULT_ENCRYPTION_KEY is missing or malformed."""


def _fernet() -> Fernet:
    raw = os.getenv("VAULT_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise VaultConfigError("Configure VAULT_ENCRYPTION_KEY with a valid Fernet key before storing vault grants")
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise VaultConfigError("VAULT_ENCRYPTION_KEY must be a valid base64-encoded 32-byte Fernet key") from exc


def vault_key_configured(environ=None) -> bool:
    """Return True when VAULT_ENCRYPTION_KEY parses as a valid Fernet key."""
    source = os.environ if environ is None else environ
    raw = source.get("VAULT_ENCRYPTION_KEY", "").strip()
    if not raw:
        return False
    try:
        Fernet(raw.encode("ascii"))
        return True
    except (ValueError, TypeError):
        return False


def encrypt_vault_token(raw_token: str) -> str:
    """Encrypt a PayPal vault token at rest; never stores or returns plaintext."""
    if not isinstance(raw_token, str) or not raw_token.strip():
        raise ValueError("Vault token must be a non-empty string")
    return _fernet().encrypt(raw_token.strip().encode("utf-8")).decode("ascii")


def decrypt_vault_token(encrypted_token: str) -> str:
    """Decrypt a Fernet-encrypted PayPal vault token."""
    if not isinstance(encrypted_token, str) or not encrypted_token.strip():
        raise VaultConfigError("Encrypted vault token is missing")
    try:
        return _fernet().decrypt(encrypted_token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise VaultConfigError("Stored vault token could not be decrypted with the current VAULT_ENCRYPTION_KEY") from exc


def mask_token(value: str | None) -> str:
    """Mask sensitive tokens and vault IDs for logs and audit details."""
    if not value or not isinstance(value, str):
        return "****"
    cleaned = value.strip()
    if len(cleaned) <= 4:
        return "****"
    return f"****{cleaned[-4:]}"

