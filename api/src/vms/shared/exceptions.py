"""
Exceções de Domínio — regras de negócio violadas.

Estas exceções representam violações de invariantes de domínio,
não erros de infraestrutura (ConnectionError, etc).

Uso:
    if not camera.is_active:
        raise BusinessRuleViolation("Câmera inativa não pode ter analytics")

    if recording not in tenant.recordings:
        raise UnauthorizedError("Usuário não pode acessar esta gravação")

    if stored_hash != current_hash:
        raise IntegrityError("Hash de integridade divergente")
"""
from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """
    Exceção base de domínio — regra de negócio violada.

    Não confunda com exceções de infraestrutura.
    DomainError indica que uma INVARIANTE de domínio foi violada.

    Atributos:
        message: Mensagem legível da violação
        details: Dicionário com contexto adicional (opcional)
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | details={self.details}"
        return self.message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.message!r})"


class NotFoundError(DomainError):
    """
    Entidade não encontrada.

    Uso:
        if not camera:
            raise NotFoundError(f"Câmera {camera_id} não encontrada")
    """
    pass


class BusinessRuleViolation(DomainError):
    """
    Regra de negócio violada (invariante do aggregate).

    Uso:
        if not camera.is_active:
            raise BusinessRuleViolation(
                "Câmera inativa não pode ter analytics",
                details={"camera_id": str(camera.id)}
            )
    """
    pass


class AuthenticationError(DomainError):
    """
    Falha de autenticação (credenciais inválidas ou token expirado).

    Uso:
        if not verify_password(password, hash):
            raise AuthenticationError("Credenciais inválidas")
    """
    pass


class UnauthorizedError(DomainError):
    """
    Ação não autorizada (permissão insuficiente).

    Diferente de NotFoundError: o recurso existe, mas o usuário
    não tem permissão para acessá-lo.

    Uso:
        if recording.tenant_id != user.tenant_id:
            raise UnauthorizedError(
                "Usuário não pode acessar gravação de outro tenant"
            )
    """
    pass


class IntegrityError(DomainError):
    """
    Violação de integridade (ex: hash divergente, dado corrompido).

    Uso:
        if stored_hash != current_hash:
            raise IntegrityError(
                "Hash de integridade divergente — arquivo pode ter sido adulterado",
                details={
                    "stored_hash": stored_hash,
                    "current_hash": current_hash,
                    "file_path": file_path,
                }
            )
    """
    pass


class ConflictError(DomainError):
    """
    Conflito de recurso (ex: slug/email já em uso no tenant).

    Uso:
        if existing:
            raise ConflictError(f"Slug '{slug}' já está em uso")
    """
    pass


class DuplicateError(ConflictError):
    """Alias semântico de ConflictError para compatibilidade."""
    pass


class StateTransitionError(DomainError):
    """
    Transição de estado inválida.

    Uso:
        if camera.status == "offline":
            raise StateTransitionError(
                "Não é possível iniciar streaming de câmera offline"
            )
    """
    pass


class ValidationError(DomainError):
    """
    Validação de dados falhou (entrada inválida ou malformada).

    Uso:
        if not camera.onvif_url:
            raise ValidationError("URL ONVIF é obrigatória")
    """
    pass
