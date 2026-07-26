"""Seed unificado: cria tenant + admin + agente.

Uso:
    python -m vms.scripts.seed \\
        --name "Rafael" \\
        --slug ops-sec \\
        --email admin@gmail.com \\
        --password admin123

NOTA (Next Sec): a versão original (vms/) também criava uma LicenseKeyModel
(billing, não copiado — fora do escopo do MVP, ver reuse-plan.md). Removido
daqui; `tenant.license_key_id` fica None até que billing seja reintroduzido,
se algum dia for.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cria tenant + admin + agente.")
    p.add_argument("--name", default="rafael", help="Nome do tenant")
    p.add_argument("--slug", default="ops-sec", help="Slug único")
    p.add_argument("--email", default="admin@gmail.com", help="Email do admin")
    p.add_argument("--password", default="admin123", help="Senha do admin")
    return p.parse_args()


async def _run(
    *,
    name: str,
    slug: str,
    email: str,
    password: str,
) -> None:
    from sqlalchemy import select

    from vms.cameras.models import AgentModel
    from vms.iam.models import ApiKeyModel, TenantModel, UserModel
    from vms.infrastructure.database import close_db, create_engine, get_db_context, init_db
    from vms.infrastructure.security import generate_api_key, hash_password

    engine = create_engine()
    init_db(engine)

    async with get_db_context() as session:
        if await session.scalar(select(TenantModel).where(TenantModel.slug == slug)):
            print(f"ERRO: slug '{slug}' já existe.", file=sys.stderr)
            sys.exit(1)
        if await session.scalar(select(UserModel).where(UserModel.email == email.lower())):
            print(f"ERRO: email '{email}' já existe.", file=sys.stderr)
            sys.exit(1)

        now = datetime.now(UTC)

        # ── Tenant ────────────────────────────────────────────────────────────
        tenant = TenantModel(
            id=str(uuid.uuid4()),
            name=name,
            slug=slug,
            is_active=True,
            onboarding_complete=True,
        )
        session.add(tenant)
        await session.flush()

        # ── Admin user ────────────────────────────────────────────────────────
        user = UserModel(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            email=email.lower(),
            hashed_password=hash_password(password),
            full_name="Administrador",
            role="admin",
            is_active=True,
        )
        session.add(user)

        # ── Agente nativo + API key ───────────────────────────────────────────
        agent_id = str(uuid.uuid4())
        agent = AgentModel(
            id=agent_id,
            tenant_id=tenant.id,
            name=f"agent-{slug}",
            status="pending",
            streams_running=0,
            streams_failed=0,
            created_at=now,
        )
        session.add(agent)

        plain_key, key_hash, prefix = generate_api_key()
        session.add(ApiKeyModel(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            owner_type="agent",
            owner_id=agent_id,
            key_hash=key_hash,
            prefix=prefix,
            is_active=True,
        ))
        await session.flush()

    print("Seed concluído.")
    print(f"  tenant         : {name} ({slug})")
    print(f"  admin email    : {email}")
    print(f"  admin password : {password}")
    print(f"  agente API key : {plain_key}")
    print()
    print("Guarde a API key do agente — não será exibida novamente.")

    await close_db()


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(
        name=args.name,
        slug=args.slug,
        email=args.email,
        password=args.password,
    ))


if __name__ == "__main__":
    main()
