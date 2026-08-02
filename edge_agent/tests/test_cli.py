"""CLI do agente — ativação síncrona a partir do instalador (ADR-018 §1).

O código de saída é contrato com o `install-licensed.ps1`: é por ele que o
instalador decide se registra o serviço ou aborta mostrando o erro ao cliente.
Se isso quebrar em silêncio, o cliente termina com uma instalação "concluída"
que nunca vai funcionar.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent.cli as cli
from agent.activation import ActivationError, AgentCredentials, CredentialStore

_OK_RESPONSE = {
    "agent_id": "agent-1",
    "api_key": "vms_chave_secreta",
    "tenant_id": "tenant-1",
    "tenant_name": "Loja X",
    "api_base_url": "https://vps.exemplo.com",
    "policy": {"clip_seconds": 15},
}


@pytest.fixture
def store_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CredentialStore:
    """Aponta o CredentialStore do CLI pro tmp_path do teste."""
    path = tmp_path / "agent.json"
    monkeypatch.setattr(cli, "CredentialStore", lambda: CredentialStore(path))
    return CredentialStore(path)


class TestActivateCommand:
    def test_success_writes_credentials_and_exits_zero(
        self, store_at: CredentialStore, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        async def _fake_activate(api_url, license_key, hostname=None):  # noqa: ANN001
            return AgentCredentials.from_dict(_OK_RESPONSE)

        monkeypatch.setattr(cli, "activate", _fake_activate)

        code = cli.main(["activate", "ABCD-12345-67890-ABCDE-FGHIJ", "--api-url", "https://vps.exemplo.com"])

        assert code == 0
        assert store_at.load().api_key == "vms_chave_secreta"
        assert "Loja X" in capsys.readouterr().out

    def test_permanent_failure_exits_one(
        self, store_at: CredentialStore, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Exit 1 = não adianta tentar de novo; o instalador aborta e mostra a
        mensagem em vez de oferecer 'tentar novamente'."""
        async def _fake_activate(api_url, license_key, hostname=None):  # noqa: ANN001
            raise ActivationError("Esta licença já está ativada em outra máquina.", retryable=False)

        monkeypatch.setattr(cli, "activate", _fake_activate)

        code = cli.main(["activate", "ABCD-12345-67890-ABCDE-FGHIJ", "--api-url", "https://vps.exemplo.com"])

        assert code == 1
        assert not store_at.exists()
        assert "outra máquina" in capsys.readouterr().err

    def test_retryable_failure_exits_two(
        self, store_at: CredentialStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_activate(api_url, license_key, hostname=None):  # noqa: ANN001
            raise ActivationError("Servidor indisponível.", retryable=True)

        monkeypatch.setattr(cli, "activate", _fake_activate)

        code = cli.main(["activate", "ABCD-12345-67890-ABCDE-FGHIJ", "--api-url", "https://vps.exemplo.com"])
        assert code == 2

    def test_already_activated_is_a_no_op(
        self, store_at: CredentialStore, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Rodar o instalador duas vezes não pode reemitir credencial à toa —
        a reemissão revoga a anterior, e um agente em execução perderia acesso."""
        store_at.save(AgentCredentials.from_dict(_OK_RESPONSE))

        def _must_not_run(*args, **kwargs):
            raise AssertionError("não deveria chamar a VPS")

        monkeypatch.setattr(cli, "activate", _must_not_run)

        assert cli.main(["activate", "ABCD-12345-67890-ABCDE-FGHIJ", "--api-url", "https://x"]) == 0
        assert "já está ativada" in capsys.readouterr().out

    def test_force_reactivates(
        self, store_at: CredentialStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store_at.save(AgentCredentials.from_dict(_OK_RESPONSE))
        called = {"n": 0}

        async def _fake_activate(api_url, license_key, hostname=None):  # noqa: ANN001
            called["n"] += 1
            return AgentCredentials.from_dict({**_OK_RESPONSE, "api_key": "vms_nova"})

        monkeypatch.setattr(cli, "activate", _fake_activate)

        assert cli.main([
            "activate", "ABCD-12345-67890-ABCDE-FGHIJ", "--api-url", "https://x", "--force",
        ]) == 0
        assert called["n"] == 1
        assert store_at.load().api_key == "vms_nova"


class TestStatusCommand:
    def test_reports_activation_without_leaking_the_api_key(
        self, store_at: CredentialStore, capsys
    ) -> None:
        """`status` é o comando que o suporte pede pro cliente colar num chat —
        imprimir a API key aqui a vazaria de rotina."""
        store_at.save(AgentCredentials.from_dict(_OK_RESPONSE))

        assert cli.main(["status"]) == 0
        out = capsys.readouterr().out
        assert "vms_chave_secreta" not in out
        assert json.loads(out)["cliente"] == "Loja X"

    def test_not_activated_exits_nonzero(self, store_at: CredentialStore, capsys) -> None:
        assert cli.main(["status"]) == 1
        assert "Não ativado" in capsys.readouterr().out

    def test_permission_denied_tells_support_not_to_reactivate(
        self, store_at: CredentialStore, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Codigo 3 (nao 1): "sem permissao" e "nao ativado" exigem acoes
        opostas, e confundi-los faz o suporte revogar a credencial de um
        agente que estava funcionando."""
        def _denied(self):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(CredentialStore, "load", _denied)

        assert cli.main(["status"]) == 3
        err = capsys.readouterr().err
        assert "administrador" in err.lower()
        assert "NÃO reative" in err


class TestFingerprintCommand:
    def test_prints_the_machine_id(self, capsys) -> None:
        assert cli.main(["fingerprint"]) == 0
        assert len(capsys.readouterr().out.strip()) == 64
