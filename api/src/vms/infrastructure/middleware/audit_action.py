"""
Decorator @audit_action — Anota endpoints com ação semântica de auditoria.

Uso:
    @audit_action("camera.created", resource_type="camera", id_param="camera_id")
    @router.post("/cameras")
    async def create_camera(body: CameraCreate, claims: CurrentUser, db: DbSession):
        ...

    @audit_action("user.deleted", resource_type="user", id_param="user_id")
    @router.delete("/users/{user_id}")
    async def delete_user(user_id: str, claims: CurrentUser, db: DbSession):
        ...

O decorator captura:
- user_id, tenant_id, role do CurrentUser
- resource_id do path param
- request_id do correlation ID
- ip_address e user_agent do request
- payload do request body (sanitizado)
- result baseado em exceções
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from fastapi import Request

logger = logging.getLogger(__name__)


def audit_action(
    action: str,
    resource_type: str | None = None,
    id_param: str | None = None,
    name_param: str | None = None,
    log_payload: bool = True,
) -> Callable:
    """
    Decorator que registra ação de auditoria após execução do endpoint.

    Args:
        action: Ação semântica (ex: "camera.created", "user.deleted")
        resource_type: Tipo do recurso (ex: "camera", "user"). Inferido da action se None.
        id_param: Nome do path param que contém o resource_id (ex: "camera_id")
        name_param: Nome do campo no response body que contém o resource_name
        log_payload: Se True, loga o payload do request (sanitizado)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extrair contexto do request
            request: Request | None = kwargs.get("request")
            claims = kwargs.get("claims")  # CurrentUser
            db = kwargs.get("db")  # DbSession

            # Extrair metadata
            user_id = getattr(claims, "user_id", None) if claims else None
            tenant_id = getattr(claims, "tenant_id", None) if claims else None
            user_role = getattr(claims, "role", None) if claims else None

            # Extrair resource_id do path param
            resource_id = kwargs.get(id_param) if id_param else None

            # Extrair IP e user_agent
            ip_address = None
            user_agent = None
            request_id = None
            if request:
                ip_address = (
                    request.headers.get("X-Real-IP")
                    or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    or (request.client.host if request.client else None)
                )
                user_agent = request.headers.get("User-Agent")
                request_id = request.headers.get("X-Request-ID")

            # Determinar resource_type
            final_resource_type = resource_type or action.split(".")[0] if "." in action else action

            result = "success"
            payload = {}
            caught_exc: Exception | None = None

            try:
                response = await func(*args, **kwargs)

                # Extrair resource_name do response se disponível
                resource_name = None
                if name_param and hasattr(response, name_param):
                    resource_name = getattr(response, name_param)
                elif isinstance(response, dict) and name_param:
                    resource_name = response.get(name_param)

                # Log de auditoria (assíncrono, não bloqueia response)
                if tenant_id:
                    try:
                        from vms.audit.repository import AuditRepository
                        from vms.audit.service import AuditService

                        if db:
                            repo = AuditRepository(db)
                            svc = AuditService(repo)
                            await svc.log(
                                tenant_id=tenant_id,
                                action=action,
                                user_id=user_id,
                                user_role=user_role,
                                resource_type=final_resource_type,
                                resource_id=resource_id,
                                resource_name=resource_name,
                                ip_address=ip_address,
                                user_agent=user_agent,
                                request_id=request_id,
                                payload=payload if log_payload else None,
                                result=result,
                            )
                    except Exception:
                        logger.critical("AUDIT LOG INSERT FAILED — action=%s tenant=%s user=%s",
                                        action, tenant_id, user_id, exc_info=True)
                        # Métrica Prometheus (se disponível)
                        try:
                            from prometheus_client import Counter
                            _audit_failures = Counter("audit_log_failures_total", "Falhas ao inserir audit log")
                            _audit_failures.inc()
                        except Exception:
                            pass  # Prometheus não disponível

                return response

            except Exception as exc:
                caught_exc = exc
                result = "error"
                raise

            finally:
                # Se houve exceção, logar o erro
                if result == "error" and tenant_id:
                    try:
                        from vms.audit.repository import AuditRepository
                        from vms.audit.service import AuditService

                        if db:
                            repo = AuditRepository(db)
                            svc = AuditService(repo)
                            await svc.log(
                                tenant_id=tenant_id,
                                action=action,
                                user_id=user_id,
                                user_role=user_role,
                                resource_type=final_resource_type,
                                resource_id=resource_id,
                                ip_address=ip_address,
                                user_agent=user_agent,
                                request_id=request_id,
                                payload={"error": str(caught_exc)} if caught_exc else None,
                                result="error",
                            )
                    except Exception:
                        logger.critical("AUDIT LOG ERROR INSERT FAILED — action=%s tenant=%s user=%s",
                                        action, tenant_id, user_id, exc_info=True)
                        try:
                            from prometheus_client import Counter
                            _audit_failures = Counter("audit_log_failures_total", "Falhas ao inserir audit log")
                            _audit_failures.inc()
                        except Exception:
                            pass

        return wrapper
    return decorator
