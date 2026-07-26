"""Configurações do analytics_service via variáveis de ambiente."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações carregadas do ambiente ou .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ─── VMS API ───────────────────────────────────────────────────────────
    vms_api_url: str = Field(default="http://localhost:8000")
    vms_api_key: str = Field(default="dev-analytics-key")
    mediamtx_host: str = Field(default="mediamtx")

    # ─── Redis ─────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/1")

    # ─── MediaMTX ──────────────────────────────────────────────────────────
    mediamtx_api_url: str = Field(default="http://localhost:9997")
    mediamtx_rtsp_port: int = Field(default=8554, description="Porta RTSP do MediaMTX")

    # ─── Analytics ─────────────────────────────────────────────────────────
    analytics_fps: int = Field(default=1, description="Frames por segundo por câmera")
    analytics_workers: int = Field(default=4, description="Workers paralelos")
    yolo_imgsz: int = Field(default=640, description="Tamanho de imagem para YOLO")
    yolo_conf: float = Field(default=0.30, description="Confiança mínima YOLO")

    # Modelos YOLO
    yolo_model_path: str = Field(default="/models/object.pt")
    lpr_model_path: str = Field(default="/models/object.pt")
    fire_smoke_model_path: str = Field(default="/models/fire.pt")
    ppe_model_path: str = Field(default="/models/ppe.pt")
    biker_model_path: str = Field(default="/models/biker_2.pt")
    horse_cart_model_path: str = Field(default="/models/horse_cart.pt")
    traffic_model_path: str = Field(default="/models/traffic.pt")
    object_model_path: str = Field(default="/models/object.pt")

    # ─── Observabilidade ───────────────────────────────────────────────────
    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> Settings:
    """Retorna settings cacheados (singleton)."""
    return Settings()
