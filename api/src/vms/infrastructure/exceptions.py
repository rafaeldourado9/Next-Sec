"""Exceções de domínio e handlers HTTP para FastAPI."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from vms.shared.exceptions import (
    AuthenticationError as SharedAuthenticationError,
    BusinessRuleViolation,
    ConflictError as SharedConflictError,
    IntegrityError,
    NotFoundError as SharedNotFoundError,
    StateTransitionError,
    UnauthorizedError as SharedUnauthorizedError,
    ValidationError as SharedValidationError,
)


# ─── Exceções de Domínio ──────────────────────────────────────────────────────

class VmsError(Exception):
    """Base de todas as exceções do VMS."""


class NotFoundError(VmsError):
    """Recurso não encontrado."""

    def __init__(self, resource: str, identifier: str | None = None) -> None:
        detail = f"{resource} não encontrado"
        if identifier:
            detail = f"{resource} '{identifier}' não encontrado"
        super().__init__(detail)
        self.resource = resource
        self.identifier = identifier


class ConflictError(VmsError):
    """Conflito — recurso já existe."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ForbiddenError(VmsError):
    """Acesso negado ao recurso do tenant."""

    def __init__(self, message: str = "Acesso negado") -> None:
        super().__init__(message)


class ValidationError(VmsError):
    """Dados de entrada inválidos."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AuthenticationError(VmsError):
    """Falha de autenticação."""

    def __init__(self, message: str = "Credenciais inválidas") -> None:
        super().__init__(message)


class ServiceUnavailableError(VmsError):
    """Serviço externo indisponível (MediaMTX, etc.)."""

    def __init__(self, service: str) -> None:
        super().__init__(f"Serviço '{service}' indisponível")
        self.service = service


# ─── Handlers HTTP ────────────────────────────────────────────────────────────

def _error_response(
    error_code: str,
    message: str,
    status_code: int,
    detail: object = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error_code, "message": message, "detail": detail},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Registra handlers de exceção no app FastAPI."""

    @app.exception_handler(NotFoundError)
    async def handle_not_found(_req: Request, exc: NotFoundError) -> JSONResponse:
        return _error_response("not_found", str(exc), status.HTTP_404_NOT_FOUND)

    @app.exception_handler(ConflictError)
    async def handle_conflict(_req: Request, exc: ConflictError) -> JSONResponse:
        return _error_response("conflict", str(exc), status.HTTP_409_CONFLICT)

    @app.exception_handler(ForbiddenError)
    async def handle_forbidden(_req: Request, exc: ForbiddenError) -> JSONResponse:
        return _error_response("forbidden", str(exc), status.HTTP_403_FORBIDDEN)

    @app.exception_handler(AuthenticationError)
    async def handle_auth(_req: Request, exc: AuthenticationError) -> JSONResponse:
        return _error_response(
            "unauthorized", str(exc), status.HTTP_401_UNAUTHORIZED
        )

    @app.exception_handler(ValidationError)
    async def handle_validation(_req: Request, exc: ValidationError) -> JSONResponse:
        return _error_response(
            "validation_error", str(exc), status.HTTP_400_BAD_REQUEST
        )

    @app.exception_handler(ServiceUnavailableError)
    async def handle_unavailable(
        _req: Request, exc: ServiceUnavailableError
    ) -> JSONResponse:
        return _error_response(
            "service_unavailable",
            str(exc),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @app.exception_handler(SharedNotFoundError)
    async def handle_shared_not_found(
        _req: Request, exc: SharedNotFoundError
    ) -> JSONResponse:
        return _error_response("not_found", str(exc), status.HTTP_404_NOT_FOUND)

    @app.exception_handler(SharedConflictError)
    async def handle_shared_conflict(
        _req: Request, exc: SharedConflictError
    ) -> JSONResponse:
        return _error_response("conflict", str(exc), status.HTTP_409_CONFLICT)

    @app.exception_handler(SharedAuthenticationError)
    async def handle_shared_auth(
        _req: Request, exc: SharedAuthenticationError
    ) -> JSONResponse:
        return _error_response("unauthorized", str(exc), status.HTTP_401_UNAUTHORIZED)

    @app.exception_handler(SharedUnauthorizedError)
    async def handle_shared_unauthorized(
        _req: Request, exc: SharedUnauthorizedError
    ) -> JSONResponse:
        return _error_response("unauthorized", str(exc), status.HTTP_401_UNAUTHORIZED)

    @app.exception_handler(SharedValidationError)
    async def handle_shared_validation(
        _req: Request, exc: SharedValidationError
    ) -> JSONResponse:
        return _error_response("validation_error", str(exc), status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(BusinessRuleViolation)
    async def handle_business_rule(
        _req: Request, exc: BusinessRuleViolation
    ) -> JSONResponse:
        return _error_response("business_rule_violation", str(exc), status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(StateTransitionError)
    async def handle_state_transition(
        _req: Request, exc: StateTransitionError
    ) -> JSONResponse:
        return _error_response("state_transition_error", str(exc), status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(IntegrityError)
    async def handle_integrity(_req: Request, exc: IntegrityError) -> JSONResponse:
        return _error_response("integrity_error", str(exc), status.HTTP_409_CONFLICT)
