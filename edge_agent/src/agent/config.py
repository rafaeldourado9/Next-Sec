"""Configuração do Edge Agent via variáveis de ambiente."""
from __future__ import annotations

from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Variáveis de ambiente do Edge Agent."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Identidade do agent no VMS
    agent_id: str
    agent_api_key: str

    # URL da VMS API (ex.: http://vms-api:8000)
    vms_api_url: AnyHttpUrl

    # Intervalo de polling de configuração (segundos)
    config_poll_interval: int = 30

    # Intervalo de heartbeat (segundos)
    heartbeat_interval: int = 15

    # URL base do MediaMTX (ex.: rtmp://mediamtx:1935)
    mediamtx_rtmp_url: str = "rtmp://mediamtx:1935"

    # Timeout HTTP (segundos)
    http_timeout: float = 10.0

    # Nível de log
    log_level: str = "INFO"

    @field_validator("config_poll_interval", "heartbeat_interval", mode="before")
    @classmethod
    def positive_int(cls, v: int) -> int:
        """Valida que o intervalo é positivo."""
        if int(v) <= 0:
            msg = "Intervalo deve ser positivo"
            raise ValueError(msg)
        return int(v)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Retorna instância singleton das configurações."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
