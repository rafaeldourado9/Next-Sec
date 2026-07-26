"""
Infrastructure — Camada de infraestrutura do VMS.

Responsabilidades:
- Configuração (variáveis de ambiente, settings)
- Database (SQLAlchemy async, engine, sessions)
- Messaging (RabbitMQ event bus, Dead Letter Queue)
- Logging (structlog configurado)
- Security (bcrypt, JWT, API keys, webhook signatures)
- Exceptions (exceções de domínio + handler FastAPI)

REGRA: Infrastructure NUNCA importa de bounded contexts.
       Ela fornece serviços técnicos para toda a aplicação.
"""
from vms.infrastructure.config import Settings, get_settings
from vms.infrastructure.database import (
    Base,
    close_db,
    create_engine,
    get_db_context,
    get_session_factory,
    init_db,
)
from vms.infrastructure.messaging import (
    DomainEventBus,
    EventRegistry,
    record_failure,
)
from vms.infrastructure.logging import setup_logging
from vms.infrastructure.exceptions import (
    VmsError,
    NotFoundError,
    ConflictError,
    ForbiddenError,
    ValidationError,
    AuthenticationError,
    ServiceUnavailableError,
    register_exception_handlers,
)
from vms.infrastructure.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    create_viewer_token,
    decode_token,
    is_token_valid,
    generate_api_key,
    verify_api_key,
    extract_key_prefix,
    sign_webhook_payload,
    verify_webhook_signature,
)

__all__ = [
    # Config
    "Settings",
    "get_settings",
    # Database
    "Base",
    "close_db",
    "create_engine",
    "get_db_context",
    "get_session_factory",
    "init_db",
    # Messaging
    "DomainEventBus",
    "EventRegistry",
    "record_failure",
    # Logging
    "setup_logging",
    # Exceptions
    "VmsError",
    "NotFoundError",
    "ConflictError",
    "ForbiddenError",
    "ValidationError",
    "AuthenticationError",
    "ServiceUnavailableError",
    "register_exception_handlers",
    # Security
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
