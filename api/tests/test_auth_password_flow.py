"""Testes HTTP do fluxo de troca de senha obrigatória (Sprint 7 — onboarding
por licença): login expõe `must_change_password`, e `PUT /auth/change-
password` é a única forma de zerá-lo. Mesmo padrão de app/client mínimo dos
outros testes HTTP desta suíte (ver test_admin_onboard_client.py)."""
from __future__ import annotations

import uuid

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.iam.models import TenantModel, UserModel
from vms.iam.router import router as iam_router
from vms.infrastructure.exceptions import register_exception_handlers
from vms.infrastructure.security import hash_password, verify_password
from vms.shared.api.dependencies import get_current_user, get_db, TokenClaims


@pytest_asyncio.fixture
async def app(db_session: AsyncSession) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(iam_router, prefix="/api/v1")
    register_exception_handlers(fastapi_app)

    async def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    return fastapi_app


@pytest_asyncio.fixture
async def client(app: FastAPI):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def onboarded_user(db_session: AsyncSession, tenant_a: TenantModel) -> UserModel:
    """Usuário criado com senha padrão + must_change_password=True — mesmo
    estado que sai de POST /admin/onboard-client."""
    user = UserModel(
        id=str(uuid.uuid4()), tenant_id=tenant_a.id, email="gestor@cliente.com",
        hashed_password=hash_password("SenhaPadrao123"), full_name="Gestor",
        role="gestor", is_active=True, must_change_password=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


class TestLoginExposesMustChangePassword:
    async def test_login_returns_must_change_password_true(
        self, client: AsyncClient, onboarded_user: UserModel
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/token",
            json={"email": onboarded_user.email, "password": "SenhaPadrao123"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["must_change_password"] is True

    async def test_login_returns_must_change_password_false_for_normal_user(
        self, client: AsyncClient, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        user = UserModel(
            id=str(uuid.uuid4()), tenant_id=tenant_a.id, email="normal@cliente.com",
            hashed_password=hash_password("SenhaNormal123"), full_name="Normal",
            role="viewer", is_active=True, must_change_password=False,
        )
        db_session.add(user)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/auth/token",
            json={"email": user.email, "password": "SenhaNormal123"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["must_change_password"] is False


class TestChangePassword:
    async def test_wrong_current_password_returns_401(
        self, app: FastAPI, client: AsyncClient, onboarded_user: UserModel
    ) -> None:
        async def _override_current_user():
            return TokenClaims(user_id=onboarded_user.id, tenant_id=onboarded_user.tenant_id, role="gestor")

        app.dependency_overrides[get_current_user] = _override_current_user

        resp = await client.put(
            "/api/v1/auth/change-password",
            json={"current_password": "SenhaErrada", "new_password": "NovaSenha456"},
        )
        assert resp.status_code == 401

    async def test_correct_current_password_clears_must_change_password(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, onboarded_user: UserModel
    ) -> None:
        async def _override_current_user():
            return TokenClaims(user_id=onboarded_user.id, tenant_id=onboarded_user.tenant_id, role="gestor")

        app.dependency_overrides[get_current_user] = _override_current_user

        resp = await client.put(
            "/api/v1/auth/change-password",
            json={"current_password": "SenhaPadrao123", "new_password": "NovaSenha456"},
        )
        assert resp.status_code == 204, resp.text

        updated = await db_session.scalar(select(UserModel).where(UserModel.id == onboarded_user.id))
        assert updated.must_change_password is False
        assert verify_password("NovaSenha456", updated.hashed_password)
        assert not verify_password("SenhaPadrao123", updated.hashed_password)
