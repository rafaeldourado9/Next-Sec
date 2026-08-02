"""Ativação do agente por chave de licença (ADR-018 §1).

Substitui a distribuição de segredos dentro do instalador: em vez de cada
cliente receber um `.zip` com API key e chave privada WireGuard, todos recebem
o **mesmo** executável e o cliente digita a licença. O agente troca a licença
por credenciais chamando `POST /edge/activate` e as grava localmente.

Três responsabilidades, deliberadamente juntas neste módulo porque nenhuma faz
sentido sozinha: obter as credenciais, guardá-las com permissão restrita, e
reconhecer quando elas deixaram de valer.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from agent.fingerprint import machine_fingerprint

logger = logging.getLogger(__name__)

AGENT_VERSION = "1.0.0"


class ActivationError(Exception):
    """Falha de ativação com mensagem destinada ao usuário final.

    A mensagem é mostrada direto no instalador, para alguém que não tem acesso
    a log nem a suporte no momento — então ela precisa dizer o que fazer, não
    só o que houve.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass
class EdgePolicy:
    """Limites que a VPS impõe a esta instalação.

    Vêm do servidor (ativação e cada heartbeat) em vez de serem configurados na
    máquina: mudar a cota de um cliente não pode exigir reinstalar nada.
    """

    events_per_minute: int = 120
    batch_max_events: int = 100
    clip_seconds: int = 15
    clip_max_height: int = 480
    clip_retention_days: int = 30
    storage_quota_mb: int = 5120
    heartbeat_seconds: int = 60
    config_poll_seconds: int = 300

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EdgePolicy:
        """Ignora campos desconhecidos: um agente antigo tem que continuar
        funcionando contra uma VPS que já aprendeu limites novos."""
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AgentCredentials:
    """O que a ativação produz — tudo que o agente precisa para operar."""

    agent_id: str
    api_key: str
    tenant_id: str
    tenant_name: str
    api_base_url: str
    policy: EdgePolicy = field(default_factory=EdgePolicy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "api_key": self.api_key,
            "tenant_id": self.tenant_id,
            "tenant_name": self.tenant_name,
            "api_base_url": self.api_base_url,
            "policy": self.policy.__dict__,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCredentials:
        return cls(
            agent_id=data["agent_id"],
            api_key=data["api_key"],
            tenant_id=data["tenant_id"],
            tenant_name=data.get("tenant_name", ""),
            api_base_url=data["api_base_url"],
            policy=EdgePolicy.from_dict(data.get("policy") or {}),
        )


def default_credentials_path() -> Path:
    """`%ProgramData%\\NextSecEdge\\agent.json` no Windows; `/etc/nextsec` no Linux."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "NextSecEdge"
    else:
        base = Path(os.environ.get("NEXTSEC_CONFIG_DIR", "/etc/nextsec"))
    return base / "agent.json"


class CredentialStore:
    """Lê e grava `agent.json`, restringindo quem consegue abri-lo.

    A API key vale enquanto a licença estiver ativa, então o arquivo é um
    segredo de longa duração num equipamento fisicamente acessível (mini-PC
    numa loja). Deixá-lo com permissão default de "todo mundo lê" anularia
    boa parte do ganho de tirar os segredos do instalador.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_credentials_path()

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.is_file()

    def load(self) -> AgentCredentials | None:
        """Credenciais gravadas, ou `None` se ainda não houver (ou estiverem
        corrompidas — nesse caso o agente reativa, que é recuperável, em vez de
        travar num arquivo ilegível)."""
        if not self._path.is_file():
            return None
        try:
            return AgentCredentials.from_dict(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            logger.warning(
                "%s ilegível ou incompleto — será necessário reativar com a licença",
                self._path, exc_info=True,
            )
            return None

    def save(self, credentials: AgentCredentials) -> None:
        """Grava e restringe o acesso ao arquivo."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(credentials.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._restrict_permissions()
        logger.info("Credenciais gravadas em %s", self._path)

    def update_policy(self, policy: EdgePolicy) -> None:
        """Persiste a policy recebida num heartbeat, preservando as credenciais.

        Sem isso, um agente reiniciado voltaria aos defaults compilados até o
        primeiro heartbeat — e enviaria clipes com a duração errada nesse
        intervalo.
        """
        current = self.load()
        if current is None:
            return
        current.policy = policy
        self.save(current)

    def _restrict_permissions(self) -> None:
        """Só SYSTEM+Administradores (Windows) / só o dono (Unix)."""
        if platform.system() == "Windows":
            try:
                # `/inheritance:r` é o que importa: sem remover a herança, as
                # ACLs permissivas de `%ProgramData%` continuariam valendo e os
                # grants abaixo não restringiriam nada.
                subprocess.run(
                    ["icacls", str(self._path), "/inheritance:r",
                     "/grant:r", "SYSTEM:F", "/grant:r", "Administrators:F"],
                    capture_output=True, timeout=15, check=False,
                )
            except Exception:
                logger.warning(
                    "Não foi possível restringir as permissões de %s — o arquivo contém "
                    "a credencial desta instalação", self._path, exc_info=True,
                )
            return

        try:
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            logger.warning("Não foi possível aplicar chmod 600 em %s", self._path, exc_info=True)


async def activate(
    api_base_url: str,
    license_key: str,
    *,
    hostname: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> AgentCredentials:
    """Troca a chave de licença por credenciais em `POST /edge/activate`.

    Traduz cada resposta de erro numa instrução acionável — quem lê está diante
    do instalador, sem suporte por perto, e "HTTP 409" não diz o que fazer.
    """
    payload = {
        "license_key": license_key.strip().upper(),
        "hardware_fingerprint": machine_fingerprint(),
        "hostname": hostname or platform.node(),
        "agent_version": AGENT_VERSION,
    }
    url = f"{api_base_url.rstrip('/')}/api/v1/edge/activate"

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    try:
        try:
            response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            msg = (
                f"Não foi possível falar com o servidor ({api_base_url}). "
                "Confira a conexão de internet desta máquina e tente de novo."
            )
            raise ActivationError(msg, retryable=True) from exc

        if response.status_code == 200:
            return AgentCredentials.from_dict(response.json())

        raise ActivationError(
            _message_for(response), retryable=response.status_code >= 500
        )
    finally:
        if owns_client:
            await client.aclose()


def _message_for(response: httpx.Response) -> str:
    """Mensagem para o usuário final a partir da resposta de erro."""
    try:
        detail = response.json().get("message") or response.json().get("detail") or ""
    except ValueError:
        detail = ""

    if response.status_code == 404:
        return "Licença não encontrada. Confira se digitou a chave exatamente como recebeu."
    if response.status_code == 409:
        return (
            "Esta licença já está ativada em outra máquina. "
            "Peça ao suporte para desvinculá-la antes de instalar aqui."
        )
    if response.status_code == 422:
        return "Formato de licença inválido — esperado XXXX-XXXXX-XXXXX-XXXXX-XXXXX."
    if response.status_code == 429:
        return "Muitas tentativas seguidas. Espere um minuto e tente de novo."
    if response.status_code >= 500:
        return "O servidor está indisponível no momento. Tente de novo em alguns minutos."
    return detail or f"Não foi possível ativar (erro {response.status_code})."


async def ensure_activated(
    api_base_url: str,
    store: CredentialStore | None = None,
    license_key: str | None = None,
) -> AgentCredentials:
    """Credenciais já gravadas, ou ativa agora se uma licença foi fornecida.

    É o ponto de entrada do agente no boot: instalação já ativada sobe direto,
    sem rede; instalação nova exige a licença.
    """
    store = store or CredentialStore()

    existing = store.load()
    if existing is not None:
        logger.info("Agente já ativado (tenant=%s)", existing.tenant_name or existing.tenant_id)
        return existing

    if not license_key:
        msg = (
            f"Este agente ainda não foi ativado e nenhuma licença foi informada. "
            f"Rode o instalador novamente com a chave de licença "
            f"(ou grave as credenciais em {store.path})."
        )
        raise ActivationError(msg)

    credentials = await activate(api_base_url, license_key)
    store.save(credentials)
    return credentials
