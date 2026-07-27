"""Gera uma chave de licença para ativação via LicenseGate (Next Sec).

Uso:
    python -m vms.scripts.create_license --email admin@example.com

A chave é criada com tenant_id=NULL — fica disponível para qualquer tenant
ativar via POST /api/v1/billing/activate (tela "Ativação de Licença"). O
--email é só para conferir/mostrar qual tenant vai consumi-la; a chave em si
não fica travada num tenant até ser ativada.
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import string
import sys

_ALPHABET = string.ascii_uppercase + string.digits


def _generate_key() -> str:
    groups = [4, 5, 5, 5, 5]
    return "-".join(
        "".join(secrets.choice(_ALPHABET) for _ in range(n)) for n in groups
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cria uma license key disponível para ativação.")
    p.add_argument("--email", default="admin@example.com", help="Email do tenant que vai ativar (só informativo)")
    p.add_argument("--deployment-model", default="self_hosted", choices=["self_hosted", "managed"])
    p.add_argument("--max-cameras", type=int, default=200)
    return p.parse_args()


async def _run(*, email: str, deployment_model: str, max_cameras: int) -> None:
    from sqlalchemy import select

    from vms.billing.models import LicenseKeyModel
    from vms.iam.models import TenantModel, UserModel
    from vms.infrastructure.database import close_db, create_engine, get_db_context, init_db

    engine = create_engine()
    init_db(engine)

    async with get_db_context() as session:
        user = await session.scalar(select(UserModel).where(UserModel.email == email.lower()))
        if not user:
            print(f"AVISO: nenhum usuário com email '{email}' encontrado — a chave será criada mesmo assim.",
                  file=sys.stderr)
            tenant = None
        else:
            tenant = await session.get(TenantModel, user.tenant_id)

        key_value = _generate_key()
        license_key = LicenseKeyModel(
            license_key=key_value,
            tenant_id=None,
            deployment_model=deployment_model,
            status="active",
            max_cameras=max_cameras,
        )
        session.add(license_key)
        await session.flush()

    print("Licença criada.")
    if tenant:
        print(f"  tenant  : {tenant.name} ({tenant.slug})")
    print(f"  email   : {email}")
    print(f"  chave   : {key_value}")
    print()
    print("Cole essa chave na tela de Ativação de Licença após login.")

    await close_db()


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(
        email=args.email,
        deployment_model=args.deployment_model,
        max_cameras=args.max_cameras,
    ))


if __name__ == "__main__":
    main()
