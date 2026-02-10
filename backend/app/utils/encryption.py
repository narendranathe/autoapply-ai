"""
Encryption utilities for storing sensitive data at rest.
"""

from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

from app.config import settings


def _get_fernet() -> Fernet | None:
    """Get Fernet instance. Returns None if key not configured."""
    if not settings.FERNET_KEY:
        logger.warning("FERNET_KEY not set — encryption disabled")
        return None
    return Fernet(settings.FERNET_KEY.encode())


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value for database storage."""
    fernet = _get_fernet()
    if fernet is None:
        raise ValueError("Encryption not configured. Set FERNET_KEY environment variable.")
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    """Decrypt a value retrieved from the database."""
    fernet = _get_fernet()
    if fernet is None:
        raise ValueError("Encryption not configured.")
    try:
        return fernet.decrypt(encrypted.encode()).decode()
    except InvalidToken as err:
        logger.error("Failed to decrypt value — key mismatch or corrupted data")
        raise ValueError("Decryption failed") from err
