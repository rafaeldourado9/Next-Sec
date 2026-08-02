"""Ativação do agente por licença (ADR-018 §1).

O que estes testes protegem, em ordem de importância: (1) o `agent.json` nasce
com permissão restrita — é um segredo de longa duração num equipamento
fisicamente acessível; (2) cada falha vira uma instrução acionável, porque quem
lê está diante do instalador sem suporte por perto; (3) um `agent.json`
corrompido leva a reativar, não a travar.
"""
from __future__ import annotations

import json
import os
import platform
import stat
from pathlib import Path

import httpx
import pytest

from agent.activation import (
    ActivationError,
    AgentCredentials,
    CredentialStore,
    EdgePolicy,
    activate,
    ensure_activated,
)
from agent.fingerprint import machine_fingerprint

# `asyncio_mode = auto` (pytest.ini) já cuida dos testes async — marcar o
# módulo inteiro faria pytest reclamar de cada teste síncrono desta suíte.

_OK_RESPONSE = {
    "agent_id": "agent-1",
    "api_key": "vms_chave_secreta",
    "tenant_id": "tenant-1",
    "tenant_name": "Loja X",
    "api_base_url": "https://vps.exemplo.com",
    "rtmp_url": "rtmp://vps.exemplo.com:1935",
    "policy": {
        "events_per_minute": 200,
        "batch_max_events": 100,
        "clip_seconds": 20,
        "clip_max_height": 480,
        "clip_retention_days": 30,
        "storage_quota_mb": 5120,
        "heartbeat_seconds": 60,
        "config_poll_seconds": 300,
    },
}


def _transport(status: int, body: dict | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body if body is not None else {})

    return httpx.MockTransport(handler)


def _client(status: int, body: dict | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=_transport(status, body))


class TestFingerprint:
    def test_is_a_sha256_hex_digest(self) -> None:
        fingerprint = machine_fingerprint()
        assert len(fingerprint) == 64
        assert all(c in "0123456789abcdef" for c in fingerprint)

    def test_is_stable_across_calls(self) -> None:
        """Se mudasse entre execuções, toda reinicialização do agente pediria
        desvínculo — o vínculo com a máquina viraria um gerador de chamados."""
        assert machine_fingerprint() == machine_fingerprint()


class TestActivate:
    async def test_returns_credentials_and_policy(self) -> None:
        async with _client(200, _OK_RESPONSE) as client:
            credentials = await activate("https://vps.exemplo.com", "ABCD-12345-67890-ABCDE-FGHIJ", client=client)

        assert credentials.api_key == "vms_chave_secreta"
        assert credentials.tenant_name == "Loja X"
        # Sem isso o agente publicaria em `rtmp://mediamtx:1935`, que só
        # resolve dentro da rede Docker da VPS — nada chegaria da casa do
        # cliente.
        assert credentials.rtmp_url == "rtmp://vps.exemplo.com:1935"
        # A policy vem do servidor, não de default compilado: mudar a cota de
        # um cliente não pode exigir reinstalar nada.
        assert credentials.policy.clip_seconds == 20
        assert credentials.policy.events_per_minute == 200

    async def test_sends_the_fingerprint_and_normalized_key(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(200, json=_OK_RESPONSE)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await activate("https://vps.exemplo.com", "  abcd-12345-67890-abcde-fghij ", client=client)

        assert captured["license_key"] == "ABCD-12345-67890-ABCDE-FGHIJ"
        assert len(captured["hardware_fingerprint"]) == 64
        assert captured["hostname"]

    async def test_unknown_policy_fields_do_not_break_an_older_agent(self) -> None:
        """Um agente instalado hoje precisa continuar funcionando contra uma
        VPS que amanhã aprendeu um limite novo."""
        body = {**_OK_RESPONSE, "policy": {**_OK_RESPONSE["policy"], "limite_do_futuro": 42}}
        async with _client(200, body) as client:
            credentials = await activate("https://vps.exemplo.com", "ABCD-12345-67890-ABCDE-FGHIJ", client=client)
        assert credentials.policy.clip_seconds == 20

    @pytest.mark.parametrize(
        ("status", "expected_fragment"),
        [
            (404, "não encontrada"),
            (409, "outra máquina"),
            (422, "Formato de licença"),
            (429, "Muitas tentativas"),
            (503, "indisponível"),
        ],
    )
    async def test_each_failure_tells_the_user_what_to_do(
        self, status: int, expected_fragment: str
    ) -> None:
        async with _client(status) as client:
            with pytest.raises(ActivationError) as exc_info:
                await activate("https://vps.exemplo.com", "ABCD-12345-67890-ABCDE-FGHIJ", client=client)
        assert expected_fragment.lower() in exc_info.value.message.lower()

    async def test_server_errors_are_marked_retryable_but_client_errors_are_not(self) -> None:
        """O instalador oferece "tentar de novo" só quando isso pode mudar o
        resultado — repetir um 409 é perda de tempo do cliente."""
        async with _client(503) as client:
            with pytest.raises(ActivationError) as server_error:
                await activate("https://vps.exemplo.com", "ABCD-12345-67890-ABCDE-FGHIJ", client=client)
        async with _client(409) as client:
            with pytest.raises(ActivationError) as conflict:
                await activate("https://vps.exemplo.com", "ABCD-12345-67890-ABCDE-FGHIJ", client=client)

        assert server_error.value.retryable is True
        assert conflict.value.retryable is False

    async def test_network_failure_mentions_the_connection(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("sem rota até o host", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ActivationError) as exc_info:
                await activate("https://vps.exemplo.com", "ABCD-12345-67890-ABCDE-FGHIJ", client=client)

        assert "internet" in exc_info.value.message.lower()
        assert exc_info.value.retryable is True


class TestCredentialStore:
    def test_roundtrip(self, tmp_path: Path) -> None:
        store = CredentialStore(tmp_path / "agent.json")
        credentials = AgentCredentials.from_dict(_OK_RESPONSE)

        store.save(credentials)
        loaded = store.load()

        assert loaded is not None
        assert loaded.api_key == credentials.api_key
        assert loaded.policy.clip_seconds == 20

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert CredentialStore(tmp_path / "agent.json").load() is None

    def test_corrupt_file_leads_to_reactivation_not_a_crash(self, tmp_path: Path) -> None:
        """Recuperável: o cliente reativa com a licença. Travar num arquivo
        ilegível exigiria alguém com acesso à máquina."""
        path = tmp_path / "agent.json"
        path.write_text("{ isto não é json", encoding="utf-8")

        assert CredentialStore(path).load() is None

    def test_unreadable_file_raises_instead_of_looking_unactivated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ACL restringe o arquivo a SYSTEM+Administradores. Uma conta sem
        acesso não pode concluir "não ativado" — isso levaria o suporte a
        reativar, revogando a credencial de um agente saudável."""
        path = tmp_path / "agent.json"
        path.write_text(json.dumps(_OK_RESPONSE), encoding="utf-8")

        def _denied(*args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "read_text", _denied)

        with pytest.raises(PermissionError):
            CredentialStore(path).load()

    def test_file_missing_required_field_is_treated_as_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "agent.json"
        path.write_text(json.dumps({"tenant_id": "t1"}), encoding="utf-8")

        assert CredentialStore(path).load() is None

    def test_creates_the_parent_directory(self, tmp_path: Path) -> None:
        store = CredentialStore(tmp_path / "sub" / "dir" / "agent.json")
        store.save(AgentCredentials.from_dict(_OK_RESPONSE))
        assert store.exists()

    @pytest.mark.skipif(platform.system() == "Windows", reason="modo POSIX não se aplica")
    def test_file_is_not_readable_by_others(self, tmp_path: Path) -> None:
        """A API key vale enquanto a licença estiver ativa, num equipamento
        fisicamente acessível — permissão default anularia boa parte do ganho
        de ter tirado os segredos do instalador."""
        store = CredentialStore(tmp_path / "agent.json")
        store.save(AgentCredentials.from_dict(_OK_RESPONSE))

        mode = stat.S_IMODE(os.stat(store.path).st_mode)
        assert mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH) == 0

    def test_update_policy_preserves_the_credentials(self, tmp_path: Path) -> None:
        """Sem persistir a policy do heartbeat, um agente reiniciado voltaria
        aos defaults compilados e enviaria clipes com a duração errada até a
        próxima batida."""
        store = CredentialStore(tmp_path / "agent.json")
        store.save(AgentCredentials.from_dict(_OK_RESPONSE))

        store.update_policy(EdgePolicy(clip_seconds=30, events_per_minute=500))

        loaded = store.load()
        assert loaded.api_key == "vms_chave_secreta"
        assert loaded.policy.clip_seconds == 30

    def test_update_policy_on_unactivated_agent_is_a_no_op(self, tmp_path: Path) -> None:
        store = CredentialStore(tmp_path / "agent.json")
        store.update_policy(EdgePolicy(clip_seconds=30))
        assert not store.exists()


class TestEnsureActivated:
    async def test_already_activated_does_not_touch_the_network(self, tmp_path: Path) -> None:
        """Boot de instalação já ativada precisa subir sem depender da VPS —
        senão uma queda de rede impediria o agente de iniciar, justamente
        quando a fila offline mais importa."""
        store = CredentialStore(tmp_path / "agent.json")
        store.save(AgentCredentials.from_dict(_OK_RESPONSE))

        credentials = await ensure_activated("https://inalcancavel.invalid", store=store)
        assert credentials.api_key == "vms_chave_secreta"

    async def test_missing_credentials_and_no_license_explains_what_to_do(
        self, tmp_path: Path
    ) -> None:
        store = CredentialStore(tmp_path / "agent.json")
        with pytest.raises(ActivationError) as exc_info:
            await ensure_activated("https://vps.exemplo.com", store=store)

        assert "licença" in exc_info.value.message.lower()
        assert str(store.path) in exc_info.value.message
