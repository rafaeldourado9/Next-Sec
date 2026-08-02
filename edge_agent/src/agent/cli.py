"""Linha de comando do agente — ativação e diagnóstico (ADR-018 §1).

Existe para o instalador poder **ativar de forma síncrona, antes** de registrar
o serviço, e mostrar o erro ao cliente na hora. A alternativa (registrar o
serviço e deixar a ativação acontecer no primeiro boot) esconderia "licença já
usada em outra máquina" dentro de um log de serviço que ninguém vai abrir —
o cliente veria uma instalação "concluída" que simplesmente não funciona.

Sem argumentos, roda o agente normalmente (comportamento anterior preservado:
é o que o serviço Windows invoca).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from agent.activation import (
    AGENT_VERSION,
    ActivationError,
    CredentialStore,
    activate,
)
from agent.fingerprint import machine_fingerprint


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="next-sec-agent",
        description="Agente Next Sec — captura, análise e envio de eventos.",
    )
    sub = parser.add_subparsers(dest="command")

    activate_cmd = sub.add_parser("activate", help="Ativa esta instalação com a chave de licença")
    activate_cmd.add_argument("license_key", help="XXXX-XXXXX-XXXXX-XXXXX-XXXXX")
    activate_cmd.add_argument(
        "--api-url", required=True, help="URL da VPS (ex.: https://app.exemplo.com)"
    )
    activate_cmd.add_argument("--hostname", default=None, help="Nome desta instalação no painel")
    activate_cmd.add_argument(
        "--force", action="store_true",
        help="Reativa mesmo se já houver credenciais gravadas nesta máquina",
    )

    sub.add_parser("status", help="Mostra o estado da ativação desta máquina")
    sub.add_parser("fingerprint", help="Imprime o identificador desta máquina (para suporte)")

    return parser


def _cmd_activate(args: argparse.Namespace) -> int:
    store = CredentialStore()
    if store.exists() and not args.force:
        print(f"Esta máquina já está ativada ({store.path}). Use --force para reativar.")
        return 0

    try:
        credentials = asyncio.run(
            activate(args.api_url, args.license_key, hostname=args.hostname)
        )
    except ActivationError as exc:
        # stderr + código de saída: é assim que o instalador PowerShell
        # distingue sucesso de falha e decide se registra o serviço.
        print(f"ERRO: {exc.message}", file=sys.stderr)
        return 2 if exc.retryable else 1

    store.save(credentials)
    print(f"Ativado com sucesso para: {credentials.tenant_name or credentials.tenant_id}")
    print(f"Credenciais gravadas em: {store.path}")
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    store = CredentialStore()
    credentials = store.load()
    if credentials is None:
        print(f"Não ativado. Nenhuma credencial válida em {store.path}.")
        return 1

    print(json.dumps({
        "ativado": True,
        "cliente": credentials.tenant_name or credentials.tenant_id,
        "agent_id": credentials.agent_id,
        "servidor": credentials.api_base_url,
        "versao": AGENT_VERSION,
        "limites": credentials.policy.__dict__,
        # A API key nunca é impressa: `status` é o comando que o suporte pede
        # pro cliente rodar e colar num chat.
    }, indent=2, ensure_ascii=False))
    return 0


def _cmd_fingerprint(_args: argparse.Namespace) -> int:
    print(machine_fingerprint())
    return 0


def _force_utf8_output() -> None:
    """Garante UTF-8 na saída, inclusive quando ela vai pra arquivo ou pipe.

    Achado ao testar o `.exe` real: quando stdout não é um console (NSSM
    redirecionando pro log do serviço, ou o instalador capturando a saída),
    o Python cai em `locale.getpreferredencoding()` — cp1252 no Windows
    brasileiro — e toda mensagem com acento chega ilegível justamente a quem
    precisa dela: o cliente lendo o motivo de a ativação ter falhado.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    """Despacha o subcomando, ou roda o agente quando não há nenhum."""
    _force_utf8_output()
    args = _build_parser().parse_args(argv)

    if args.command == "activate":
        return _cmd_activate(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "fingerprint":
        return _cmd_fingerprint(args)

    from agent.main import main as run_agent

    run_agent()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
