"""Configurações da aplicação via variáveis de ambiente."""

from functools import lru_cache

from pydantic import AnyUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações carregadas do ambiente ou arquivo .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ─── Ambiente ──────────────────────────────────────────────────────────
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    debug: bool = Field(default=False)

    # ─── Banco de dados ────────────────────────────────────────────────────
    database_url: str = Field(default="postgresql+asyncpg://vms:vmsdev@localhost:5432/vms")

    # ─── Redis ────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ─── RabbitMQ ─────────────────────────────────────────────────────────
    rabbitmq_url: str = Field(default="amqp://vms:vmsdev@localhost:5672/")

    # ─── Segurança ────────────────────────────────────────────────────────
    secret_key: str = Field(default="dev-secret-change-in-production")
    access_token_expire_minutes: int = Field(default=15)
    refresh_token_expire_days: int = Field(default=7)
    cors_origins: str = Field(default="https://app.vms.io")  # Separado por vírgulas
    encryption_key: str = Field(
        default="dev-encryption-key-change-in-production"
    )  # Fernet key 32 bytes base64

    # ─── MediaMTX ─────────────────────────────────────────────────────────
    mediamtx_api_url: str = Field(default="http://localhost:9997")
    mediamtx_rtmp_url: str = Field(default="rtmp://localhost:1935")

    # URL pública RTMP exposta ao integrador (câmeras RTMP push)
    # Em produção: rtmp://vms.seudominio.com.br:1935
    rtmp_public_url: str = Field(default="rtmp://localhost:1935")

    # Host interno do MediaMTX para captura de thumbnails via HLS
    mediamtx_hls_url: str = Field(default="http://mediamtx:8888")

    # ─── Analytics ────────────────────────────────────────────────────────
    analytics_api_key: str = Field(default="dev-analytics-key")
    # Endpoint HTTP interno do serviço analytics (busca facial sob demanda)
    analytics_internal_url: str = Field(default="http://analytics:8001")

    # NOTA (Next Sec): recordings_path/recordings_disk_quota_pct e o bucket
    # minio_bucket_recordings vinham do vms/ para gravação contínua (fora do
    # escopo do Next Sec — ver reuse-plan.md). Mantidos como campos (não
    # fazem mal existirem sem uso), mas nenhum código do Next Sec deve
    # depender deles — usar minio_bucket_snapshots/minio_bucket_clips.
    recordings_path: str = Field(default="/recordings")
    recordings_disk_quota_pct: float = Field(default=0.85, ge=0.5, le=0.99)

    # ─── MinIO (staging antes do StorageProvider final — ver ADR-010) ─────
    minio_endpoint: str = Field(default="http://localhost:9000")
    minio_access_key: str = Field(default="minioadmin")
    minio_secret_key: str = Field(default="miniosecret")
    minio_bucket_recordings: str = Field(default="vms-recordings")
    minio_bucket_thumbnails: str = Field(default="vms-thumbnails")
    minio_bucket_snapshots: str = Field(default="nextsec-snapshots")
    minio_bucket_analytics: str = Field(default="nextsec-analytics")
    minio_bucket_clips: str = Field(default="nextsec-clips")
    minio_bucket_exports: str = Field(default="vms-exports")

    # ─── Storage Provider (destino final do clipe — ADR-010 revisado) ──────
    storage_provider: str = Field(default="local")
    clip_retention_days: int = Field(default=30)

    # ─── Notification Channel (canal de alerta ao contato — ADR-009) ───────
    notification_channel: str = Field(default="whatsapp")
    arcanum_base_url: str = Field(default="http://arcanum:3100")
    arcanum_instance_name: str = Field(default="next-sec")

    # ─── ALPR ─────────────────────────────────────────────────────────────
    alpr_dedup_ttl_seconds: int = Field(default=60)
    alpr_min_confidence: float = Field(default=0.80)

    # ─── Limites ──────────────────────────────────────────────────────────
    max_cameras: int = Field(default=200)

    @field_validator("environment")
    @classmethod
    def validar_ambiente(cls, v: str) -> str:
        """Valida que o ambiente é um valor conhecido."""
        ambientes_validos = {"development", "staging", "production", "testing"}
        if v not in ambientes_validos:
            raise ValueError(f"Ambiente deve ser um de: {ambientes_validos}")
        return v

    @property
    def is_production(self) -> bool:
        """Retorna True se o ambiente for produção."""
        return self.environment == "production"

    @property
    def database_url_sync(self) -> str:
        """URL síncrona do banco (para Alembic)."""
        return self.database_url.replace("+asyncpg", "+psycopg2")


@lru_cache
def get_settings() -> Settings:
    """Retorna instância singleton de Settings."""
    return Settings()
