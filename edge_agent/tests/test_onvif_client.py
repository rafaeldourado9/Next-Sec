"""WS-Security UsernameToken (PasswordDigest) do cliente ONVIF.

Achado testando uma câmera ONVIF real, comprada no varejo (não um cenário
hipotético): o modo anterior (`PasswordText`, senha em texto plano no XML)
era rejeitado com HTTP 400. Confirmado empiricamente que o problema era o
formato do header, não as credenciais em si — a mesma câmera, sem NENHUM
header de auth, responde 401 (endpoint exige autenticação, mensagem aceita).
`PasswordDigest` é o modo que implementações ONVIF de verdade, em geral,
exigem — este arquivo trava a implementação exata do algoritmo
(`Base64(SHA1(nonce || created || password))`, WS-Security UsernameToken
Profile 1.0) contra regressão.
"""
from __future__ import annotations

import base64
import hashlib
import re

from agent.onvif_client import _wsa_credentials


def _extract(tag: str, xml: str) -> str:
    match = re.search(rf"<{tag}[^>]*>([^<]*)</{tag}>", xml)
    assert match, f"tag <{tag}> não encontrada no header gerado:\n{xml}"
    return match.group(1)


class TestPasswordDigest:
    def test_empty_username_produces_no_header(self) -> None:
        """Comportamento preservado: probe sem credenciais continua anônimo."""
        assert _wsa_credentials("", "") == ""

    def test_header_contains_username_verbatim(self) -> None:
        header = _wsa_credentials("admin", "hunter2")
        assert _extract("Username", header) == "admin"

    def test_password_type_is_digest_not_plaintext(self) -> None:
        """A regressão específica que motivou a mudança: câmeras reais
        rejeitam PasswordText com HTTP 400."""
        header = _wsa_credentials("admin", "hunter2")
        assert "PasswordDigest" in header
        assert "PasswordText" not in header
        # A senha em si nunca aparece em texto plano no XML.
        assert "hunter2" not in header

    def test_digest_matches_the_ws_security_algorithm(self) -> None:
        """Recomputa o digest a partir do Nonce/Created realmente emitidos
        e confere contra a fórmula do padrão — não só que o formato XML
        parece certo, mas que o valor é matematicamente correto."""
        header = _wsa_credentials("admin", "hunter2")

        nonce_b64 = _extract("Nonce", header)
        created = _extract("wsu:Created", header)
        digest_b64 = _extract("Password", header)

        nonce = base64.b64decode(nonce_b64)
        expected = hashlib.sha1(nonce + created.encode("utf-8") + b"hunter2").digest()  # noqa: S324
        assert base64.b64decode(digest_b64) == expected

    def test_created_is_utc_iso8601_with_z_suffix(self) -> None:
        """Formato específico exigido pelo WS-Security Utility namespace —
        um offset `+00:00` em vez de `Z`, por exemplo, quebra em
        implementações estritas."""
        header = _wsa_credentials("admin", "hunter2")
        created = _extract("wsu:Created", header)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", created)

    def test_nonce_differs_across_calls(self) -> None:
        """Proteção contra replay só existe se o nonce for de fato
        aleatório por request — travar isso evita uma regressão que
        "funciona" nos outros testes mas reintroduz reuso de nonce."""
        first = _extract("Nonce", _wsa_credentials("admin", "hunter2"))
        second = _extract("Nonce", _wsa_credentials("admin", "hunter2"))
        assert first != second

    def test_special_characters_in_password_do_not_break_the_digest(self) -> None:
        """A senha da câmera testada nesta sessão tinha `@` — string
        interpolada direto no XML em outro lugar do módulo já trata isso
        (é texto, não atributo), mas o digest em si precisa usar os bytes
        exatos da senha, sem qualquer escaping/normalização no meio."""
        header = _wsa_credentials("admin", "98403772R@f")
        nonce = base64.b64decode(_extract("Nonce", header))
        created = _extract("wsu:Created", header)
        expected = hashlib.sha1(nonce + created.encode("utf-8") + "98403772R@f".encode("utf-8")).digest()  # noqa: S324
        assert base64.b64decode(_extract("Password", header)) == expected
