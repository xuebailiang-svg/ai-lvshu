"""
Helpers for storing sensitive configuration values.

Values encrypted by this module are prefixed so existing plaintext database
rows can still be read during upgrades.
"""
import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)

ENCRYPTED_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_config_value(value: Optional[str]) -> Optional[str]:
    """Encrypt a config value unless it is empty or already encrypted."""
    if value is None or value == "" or value.startswith(ENCRYPTED_PREFIX):
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{ENCRYPTED_PREFIX}{token}"


def decrypt_config_value(value: Optional[str]) -> Optional[str]:
    """Decrypt a config value; plaintext legacy values are returned as-is."""
    if value is None or not value.startswith(ENCRYPTED_PREFIX):
        return value
    token = value[len(ENCRYPTED_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as e:
        logger.warning("配置值解密失败，返回空值: %s", e)
        return ""
