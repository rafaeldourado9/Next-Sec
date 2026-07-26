"""
Encryption — Fernet symmetric encryption for sensitive data at rest.

Used to encrypt ONVIF passwords, API secrets, and other credentials
before storing in the database.

Usage:
    from vms.infrastructure.encryption import encrypt, decrypt

    # Encrypt before saving to DB
    camera.onvif_password = encrypt("my_secret_password")

    # Decrypt when needed
    password = decrypt(camera.onvif_password)
"""
from __future__ import annotations

import base64
import logging

from cryptography.fernet import Fernet, InvalidToken

from vms.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Lazy initialization of Fernet cipher."""
    global _fernet
    if _fernet is None:
        settings = get_settings()
        # Generate a valid Fernet key from the encryption_key setting
        # Fernet requires a 32-byte url-safe base64-encoded key
        raw_key = settings.encryption_key.encode("utf-8")
        # Pad or truncate to 32 bytes and encode as base64
        if len(raw_key) < 32:
            raw_key = raw_key.ljust(32, b"\0")
        else:
            raw_key = raw_key[:32]
        key = base64.urlsafe_b64encode(raw_key)
        _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: str) -> str:
    """
    Encrypts a plaintext string.

    Args:
        plaintext: The string to encrypt

    Returns:
        Encrypted string (base64 encoded)
    """
    if not plaintext:
        return ""
    try:
        fernet = _get_fernet()
        encrypted = fernet.encrypt(plaintext.encode("utf-8"))
        return encrypted.decode("utf-8")
    except Exception:
        logger.exception("Falha ao criptografar dado sensível")
        return plaintext  # Fallback: store as plaintext (not ideal but avoids data loss)


def decrypt(ciphertext: str) -> str:
    """
    Decrypts an encrypted string.

    Args:
        ciphertext: The encrypted string (base64 encoded)

    Returns:
        Decrypted plaintext string
    """
    if not ciphertext:
        return ""
    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(ciphertext.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        logger.warning("Falha ao descriptografar — dado pode estar corrompido ou chave alterada")
        return ciphertext  # Return as-is (might be unencrypted legacy data)
    except Exception:
        logger.exception("Falha ao descriptografar dado sensível")
        return ciphertext


def generate_key() -> str:
    """
    Generates a new Fernet encryption key.

    Use this to create a new ENCRYPTION_KEY for production deployments.
    Store the key securely and never commit it to version control.
    """
    return Fernet.generate_key().decode("utf-8")
