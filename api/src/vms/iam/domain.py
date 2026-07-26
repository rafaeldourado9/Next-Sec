"""Entidades de domínio do IAM — puras, sem dependências externas."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class UserRole(StrEnum):
    """Papéis de usuário no sistema.

    Hierarquia: admin > gestor > operador
    """

    ADMIN = "admin"
    GESTOR = "gestor"
    OPERADOR = "operador"
    # Aliases para compatibilidade retroativa
    OPERATOR = "operator"
    VIEWER = "viewer"


class ApiKeyOwnerType(StrEnum):
    """Tipo de dono de uma API key."""

    AGENT = "agent"
    ANALYTICS = "analytics"
    WEBHOOK = "webhook"


@dataclass
class Tenant:
    """
    Tenant — unidade de isolamento multi-tenant.

    Cada tenant representa um cliente/integrador independente.
    Todos os dados são isolados por tenant_id.
    """

    id: str
    name: str
    slug: str
    is_active: bool = True
    facial_recognition_enabled: bool = False  # LGPD: off por padrão
    facial_recognition_consent_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def enable_facial_recognition(self, consent_at: datetime) -> None:
        """
        Habilita reconhecimento facial com registro de consentimento LGPD.

        Requer consentimento explícito antes de habilitar.
        """
        self.facial_recognition_enabled = True
        self.facial_recognition_consent_at = consent_at


@dataclass
class User:
    """Usuário autenticável ligado a um tenant."""

    id: str
    tenant_id: str
    email: str
    hashed_password: str
    full_name: str
    role: UserRole
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)

    def has_permission(self, required_role: UserRole) -> bool:
        """
        Verifica se o usuário tem pelo menos o papel requerido.

        Hierarquia: admin > operator > viewer
        """
        hierarchy = [UserRole.VIEWER, UserRole.OPERATOR, UserRole.ADMIN]
        user_level = hierarchy.index(self.role)
        required_level = hierarchy.index(required_role)
        return user_level >= required_level


@dataclass
class ApiKey:
    """
    API Key para autenticação machine-to-machine.

    O valor plain é gerado uma vez e nunca armazenado.
    Apenas o hash bcrypt e o prefixo são persistidos.
    """

    id: str
    tenant_id: str
    owner_type: ApiKeyOwnerType
    owner_id: str
    key_hash: str
    prefix: str  # primeiros 12 chars (ex: "vms_abc12345")
    is_active: bool = True
    last_used_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def revoke(self) -> None:
        """Revoga a API key (irreversível)."""
        self.is_active = False
