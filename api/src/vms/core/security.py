"""
⚠️ DEPRECATED: vms.core.security foi movido para vms.infrastructure.security

Este módulo existe apenas para compatibilidade durante a migração.
Todos os imports devem ser atualizados para:
    from vms.infrastructure.security import hash_password, create_access_token, decode_token, ...

Este arquivo será removido na Sprint A3.
"""
# Compatibilidade — redireciona para novo local
from vms.infrastructure.security import (  # noqa: F401
    create_access_token,
    create_refresh_token,
    create_viewer_token,
    decode_token,
    extract_key_prefix,
    generate_api_key,
    hash_password,
    is_token_valid,
    sign_webhook_payload,
    verify_api_key,
    verify_password,
    verify_webhook_signature,
)

__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "create_viewer_token",
    "decode_token",
    "is_token_valid",
    "generate_api_key",
    "verify_api_key",
    "extract_key_prefix",
    "sign_webhook_payload",
    "verify_webhook_signature",
]
