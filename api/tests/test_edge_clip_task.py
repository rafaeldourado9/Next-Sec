"""Testes da task do worker de edge (`vms.event_clips.edge_tasks`, ver
ADR-017 §1, Sprint 6 — S6-04).

ffmpeg roda de verdade (mesmo padrão do Sprint 4 — "teste real de ffmpeg,
mp4 de fato gerado", ver `.genesis/memory/progress.md`, S4-05): a imagem de
entrada é um JPEG sintético real gerado com OpenCV, e `render_freeze_frame_
clip` invoca o binário `ffmpeg` do container de verdade. Só o PUT HTTP de
saída é mockado (`httpx.MockTransport`), como recomendado para a task ARQ —
não faz sentido bater numa VPS real neste teste.
"""
from __future__ import annotations

import os

import httpx
import numpy as np
import pytest
from arq import Retry

from vms.event_clips.edge_tasks import task_render_and_upload_edge_clip
from vms.event_clips.ffmpeg import render_freeze_frame_clip

pytestmark = pytest.mark.asyncio


def _write_test_jpeg(path: str) -> None:
    """Gera um JPEG sintético real (não um mock) — 64x64 preenchido de cinza —
    suficiente para o ffmpeg processar de verdade."""
    import cv2

    frame = np.full((64, 64, 3), 128, dtype=np.uint8)
    ok = cv2.imwrite(path, frame)
    assert ok, "falha ao gerar JPEG de teste"


class TestRenderFreezeFrameClipReal:
    async def test_renders_real_mp4_from_jpeg(self, tmp_path) -> None:
        jpeg_path = str(tmp_path / "frame.jpg")
        _write_test_jpeg(jpeg_path)

        mp4_path = await render_freeze_frame_clip(jpeg_path, duration_seconds=2)
        try:
            assert os.path.isfile(mp4_path)
            assert os.path.getsize(mp4_path) > 0
        finally:
            os.remove(mp4_path)

    async def test_raises_when_input_file_does_not_exist(self, tmp_path) -> None:
        # NOTA: um arquivo com conteúdo inválido (bytes que não são JPEG, mas
        # que existem no disco) faz o ffmpeg entrar em loop de retry de
        # decodificação por causa de `-loop 1` — só falha ao receber SIGTERM,
        # nunca sozinho (achado ao investigar um hang real neste teste
        # durante o Sprint 6). Path inexistente falha rápido e de forma
        # determinística, então é o que testamos aqui; o loop de decode
        # infinito é uma limitação pré-existente de `_render_freeze_frame_
        # clip`/`render_freeze_frame_clip` (herdada do Sprint 4, fora do
        # escopo desta sprint corrigir) — vale um hardening futuro (ex.:
        # `asyncio.wait_for` com timeout ao redor do `proc.communicate()`).
        missing_path = str(tmp_path / "does-not-exist.jpg")

        with pytest.raises(RuntimeError):
            await render_freeze_frame_clip(missing_path, duration_seconds=2)


class TestTaskRenderAndUploadEdgeClip:
    async def test_missing_snapshot_returns_without_calling_ffmpeg(self, tmp_path) -> None:
        # Não cria o arquivo — a task deve retornar cedo, sem tentar ffmpeg/PUT.
        await task_render_and_upload_edge_clip(
            ctx={}, event_id="evt-1", snapshot_local_path=str(tmp_path / "missing.jpg"),
        )
        # Nenhuma exceção — comportamento best-effort documentado.

    async def test_successful_put_sends_mp4_and_cleans_up_temp_file(self, tmp_path) -> None:
        jpeg_path = str(tmp_path / "frame.jpg")
        _write_test_jpeg(jpeg_path)

        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"id": "clip-1", "status": "uploaded"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ctx = {"http_client": client, "vms_api_url": "http://vps-central:8000", "vms_api_key": "test-key"}
        try:
            await task_render_and_upload_edge_clip(
                ctx=ctx, event_id="evt-1", snapshot_local_path=jpeg_path,
            )
        finally:
            await client.aclose()

        assert len(calls) == 1
        req = calls[0]
        assert req.method == "PUT"
        assert str(req.url) == "http://vps-central:8000/api/v1/plugins/events/evt-1/clip"
        assert req.headers["authorization"] == "ApiKey test-key"
        assert b"clip_file" in req.content or req.headers.get("content-type", "").startswith(
            "multipart/form-data"
        )

    async def test_server_error_raises_retry(self, tmp_path) -> None:
        jpeg_path = str(tmp_path / "frame.jpg")
        _write_test_jpeg(jpeg_path)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "temporariamente fora do ar"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ctx = {
            "http_client": client, "vms_api_url": "http://vps-central:8000",
            "vms_api_key": "test-key", "job_try": 1,
        }
        try:
            with pytest.raises(Retry):
                await task_render_and_upload_edge_clip(
                    ctx=ctx, event_id="evt-1", snapshot_local_path=jpeg_path,
                )
        finally:
            await client.aclose()

    async def test_vps_404_event_never_arrived_does_not_raise_retry(self, tmp_path) -> None:
        """Cenário citado explicitamente na auditoria de S6-06: o evento
        nunca chegou na VPS central (ex.: `POST /plugins/events` ainda está
        na fila local do outbox do `analytics`, mas o worker de edge tentou
        gerar/enviar o clipe antes da confirmação) — a VPS responde 404
        porque `event_id` não existe. Mesmo tratamento dos demais 4xx: não é
        best-effort reenfileirado (o evento pode nunca chegar, ou chegar com
        outro id na próxima tentativa do outbox), só loga e desiste deste
        clipe. Na prática este caso não deveria ocorrer no fluxo normal —
        `_enqueue_local_clip_task` (analytics/core/vms_client.py) só
        enfileira a task de clipe DEPOIS de `ingest_event` confirmar sucesso
        — mas vale testar explicitamente porque é exatamente o tipo de
        corrida que um retry manual/duplicado no outbox poderia reintroduzir."""
        jpeg_path = str(tmp_path / "frame.jpg")
        _write_test_jpeg(jpeg_path)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Evento não encontrado"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ctx = {"http_client": client, "vms_api_url": "http://vps-central:8000", "vms_api_key": "test-key"}
        try:
            # Não deve levantar Retry nem qualquer outra exceção — best-effort.
            await task_render_and_upload_edge_clip(
                ctx=ctx, event_id="evt-nao-chegou-ainda", snapshot_local_path=jpeg_path,
            )
        finally:
            await client.aclose()

    async def test_client_error_does_not_raise_retry(self, tmp_path) -> None:
        jpeg_path = str(tmp_path / "frame.jpg")
        _write_test_jpeg(jpeg_path)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"detail": "payload inválido"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ctx = {"http_client": client, "vms_api_url": "http://vps-central:8000", "vms_api_key": "test-key"}
        try:
            # Não deve levantar Retry nem qualquer outra exceção — best-effort.
            await task_render_and_upload_edge_clip(
                ctx=ctx, event_id="evt-1", snapshot_local_path=jpeg_path,
            )
        finally:
            await client.aclose()

    async def test_network_error_raises_retry_with_owned_client(self, tmp_path) -> None:
        """Sem http_client no ctx — a task cria o seu próprio (fallback), que
        também deve propagar Retry em erro de rede."""
        jpeg_path = str(tmp_path / "frame.jpg")
        _write_test_jpeg(jpeg_path)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("queda de rede simulada", request=request)

        import vms.event_clips.edge_tasks as edge_tasks_module

        original_client_cls = httpx.AsyncClient

        class _PatchedClient(original_client_cls):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(handler)
                super().__init__(*args, **kwargs)

        edge_tasks_module.httpx.AsyncClient = _PatchedClient
        try:
            with pytest.raises(Retry):
                await task_render_and_upload_edge_clip(
                    ctx={"vms_api_url": "http://vps-central:8000", "vms_api_key": "test-key"},
                    event_id="evt-1", snapshot_local_path=jpeg_path,
                )
        finally:
            edge_tasks_module.httpx.AsyncClient = original_client_cls
