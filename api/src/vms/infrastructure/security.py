"""Utilitários de segurança: JWT, API keys, HMAC, WireGuard."""

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from jose import JWTError, jwt

from vms.infrastructure.config.settings import get_settings

# Algoritmo JWT
_ALGORITHM = "HS256"

# Prefixo de API keys — facilita identificação em logs
_API_KEY_PREFIX = "vms_"


# ─── Senhas ───────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Gera hash bcrypt da senha."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verifica senha contra hash bcrypt."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ─── JWT ─────────────────────────────────────────────────────────────────────

def create_access_token(
    subject: str,
    tenant_id: str,
    role: str,
    expire_minutes: int | None = None,
    extra_claims: dict | None = None,
) -> str:
    """Emite access token JWT com claims de identidade.

    extra_claims: claims adicionais (ex.: {'impersonated_by': admin_id})
    """
    settings = get_settings()
    expire_delta = expire_minutes or settings.access_token_expire_minutes

    payload: dict = {
        "sub": subject,
        "tenant_id": tenant_id,
        "role": role,
        "type": "access",
        "exp": datetime.now(UTC) + timedelta(minutes=expire_delta),
        "iat": datetime.now(UTC),
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


def create_refresh_token(subject: str, tenant_id: str) -> str:
    """Emite refresh token JWT de longa duração."""
    settings = get_settings()

    payload = {
        "sub": subject,
        "tenant_id": tenant_id,
        "type": "refresh",
        "exp": datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
        "iat": datetime.now(UTC),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


def create_viewer_token(tenant_id: str, camera_id: str) -> str:
    """Emite token JWT de curta duração para viewer de stream."""
    settings = get_settings()

    payload = {
        "sub": camera_id,
        "tenant_id": tenant_id,
        "camera_id": camera_id,
        "type": "viewer",
        "exp": datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": datetime.now(UTC),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


def create_playback_token(
    tenant_id: str, camera_id: str, start: str, end: str
) -> str:
    """Emite token JWT pra acessar o VOD de um intervalo específico
    (`/mediamtx-playback/`, validado via nginx auth_request).

    `start`/`end` (RFC3339) ficam embutidos no token — um token vazado só
    serve pro mesmo intervalo que foi pedido, não dá acesso a qualquer
    trecho da câmera. 60min de validade: mais longo que o viewer_token de
    live (sessão de revisão de gravação tende a durar mais que assistir ao
    vivo, com pausas/scrub).
    """
    settings = get_settings()

    payload = {
        "sub": camera_id,
        "tenant_id": tenant_id,
        "camera_id": camera_id,
        "start": start,
        "end": end,
        "type": "playback",
        "exp": datetime.now(UTC) + timedelta(minutes=60),
        "iat": datetime.now(UTC),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decodifica e valida JWT. Lança JWTError se inválido."""
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])


def is_token_valid(token: str, expected_type: str = "access") -> bool:
    """Retorna True se o token for válido e do tipo esperado."""
    try:
        payload = decode_token(token)
        return payload.get("type") == expected_type
    except JWTError:
        return False


# ─── API Keys ─────────────────────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str, str]:
    """
    Gera uma nova API key.

    Retorna:
        tuple: (plain_key, key_hash, prefix)
        - plain_key: valor completo, mostrado UMA vez ao usuário
        - key_hash: hash bcrypt para armazenar no banco
        - prefix: primeiros 12 chars (para lookup)
    """
    raw = secrets.token_urlsafe(32)
    plain_key = f"{_API_KEY_PREFIX}{raw}"
    prefix = plain_key[:12]
    key_hash = bcrypt.hashpw(plain_key.encode(), bcrypt.gensalt()).decode()
    return plain_key, key_hash, prefix


def verify_api_key(plain: str, hashed: str) -> bool:
    """Verifica API key contra hash armazenado."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def extract_key_prefix(plain_key: str) -> str:
    """Extrai o prefixo de busca de uma API key."""
    return plain_key[:12]


# ─── WireGuard (túnel do agent — ver ADR do túnel) ────────────────────────────

def generate_wg_keypair() -> tuple[str, str]:
    """
    Gera um par de chaves WireGuard (Curve25519, mesmo formato de `wg genkey`
    / `wg pubkey` — raw 32 bytes, base64). `cryptography` já é dependência
    transitiva via `python-jose[cryptography]`, então isso não precisa do
    binário `wireguard-tools` instalado no container da API.

    Retorna:
        tuple: (private_key_b64, public_key_b64) — a privada é devolvida
        ao chamador uma única vez e NUNCA deve ser persistida (mesmo
        contrato de `generate_api_key`).
    """
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    priv_bytes = private_key.private_bytes(
        encoding=Encoding.Raw, format=PrivateFormat.Raw, encryption_algorithm=NoEncryption(),
    )
    pub_bytes = public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    return base64.b64encode(priv_bytes).decode(), base64.b64encode(pub_bytes).decode()


# ─── HMAC para webhooks de saída ──────────────────────────────────────────────

def sign_webhook_payload(body: bytes, secret: str) -> str:
    """
    Gera assinatura HMAC-SHA256 para webhook de saída.

    O receptor deve verificar com:
        expected = sign_webhook_payload(body, shared_secret)
        hmac.compare_digest(received_signature, expected)
    """
    return hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()


def verify_webhook_signature(body: bytes, secret: str, signature: str) -> bool:
    """Verifica assinatura HMAC-SHA256 recebida de forma segura (timing-safe)."""
    expected = sign_webhook_payload(body, secret)
    return hmac.compare_digest(expected, signature)
