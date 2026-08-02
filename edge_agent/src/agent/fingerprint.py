"""Identidade estável da máquina, usada para vincular a licença (ADR-018 §1).

O vínculo licença↔máquina é o que impede uma licença vendida de virar N
instalações. Para isso, o identificador precisa de duas propriedades em
tensão:

- **Estável** — não pode mudar sozinho, senão toda atualização de Windows
  vira um chamado de suporte pedindo desvínculo.
- **Difícil de forjar sem querer** — não pode ser algo que duas máquinas
  clonadas (imagem de disco replicada num lote de mini-PCs, cenário
  plausível em instalação comercial) compartilhem.

A escolha é o **UUID de sistema da placa-mãe** (`MachineGuid` no Windows,
`/etc/machine-id` no Linux), com o hostname como último recurso. Deliberadamente
**não** entram na conta: MAC de rede (muda com adaptador USB/VPN, e é trivial de
alterar), número de série de disco (troca de HD é manutenção rotineira) e
qualquer coisa derivada de hardware que o cliente troque sem trocar de máquina.
Ou seja: erra para o lado de "continua valendo" em vez de "invalidou sozinho" —
o vínculo existe para dificultar cópia, não para ser um dongle.
"""
from __future__ import annotations

import hashlib
import logging
import platform
import subprocess
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Muda o hash de todas as instalações se for alterado — só faça isso se o
# esquema de fingerprint mudar de forma incompatível de propósito.
_NAMESPACE = "next-sec-edge-v1"


def machine_fingerprint() -> str:
    """SHA-256 (hex, 64 chars) da identidade da máquina."""
    raw = _machine_id() or _fallback_id()
    digest = hashlib.sha256(f"{_NAMESPACE}:{raw}".encode()).hexdigest()
    logger.debug("Fingerprint da máquina: %s…", digest[:12])
    return digest


def _machine_id() -> str | None:
    """UUID de sistema — o identificador mais estável disponível."""
    system = platform.system()
    if system == "Windows":
        return _windows_machine_guid()
    return _linux_machine_id()


def _windows_machine_guid() -> str | None:
    """`HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid` — gerado na
    instalação do Windows e preservado por updates."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value).strip() or None
    except Exception:
        logger.debug("MachineGuid indisponível — tentando o UUID do chassi", exc_info=True)

    # Reinstalar o Windows gera um MachineGuid novo; o UUID do chassi (SMBIOS)
    # sobrevive a isso, então serve de reforço quando o registro falha.
    try:
        result = subprocess.run(
            ["wmic", "csproduct", "get", "UUID"],
            capture_output=True, text=True, timeout=10,
        )
        lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        if len(lines) > 1 and lines[1].lower() not in ("", "ffffffff-ffff-ffff-ffff-ffffffffffff"):
            return lines[1]
    except Exception:
        logger.debug("UUID do chassi indisponível via wmic", exc_info=True)

    return None


def _linux_machine_id() -> str | None:
    """`/etc/machine-id` (systemd) ou `/var/lib/dbus/machine-id`."""
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            continue
    return None


def _fallback_id() -> str:
    """Último recurso, quando nenhum ID de sistema está acessível.

    `uuid.getnode()` cai no MAC (ou num valor aleatório se nem isso houver),
    o que é justamente o que o resto deste módulo evita — combinado com o
    hostname ainda dá um identificador razoável, mas pode invalidar sozinho se
    o cliente trocar de adaptador de rede. Fica registrado em WARNING para o
    suporte reconhecer esse caso quando ele aparecer.
    """
    logger.warning(
        "Nenhum UUID de sistema acessível — usando hostname+MAC como fingerprint. "
        "Este vínculo é menos estável e pode exigir novo desvínculo se o "
        "hardware de rede mudar."
    )
    return f"{platform.node()}:{uuid.getnode():x}"
