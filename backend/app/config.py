"""应用配置 - 从 .env 加载"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # DeepSeek API
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    model_customer: str = "deepseek-v4-flash"
    model_scorer: str = "deepseek-v4-pro"
    model_vision: str = "deepseek-v4-flash-vision-exp"

    # 数据库
    database_url: str = "sqlite+aiosqlite:///./drill.db"
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret: str = "please-change-this-to-a-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    #: 设计师端令牌有效期（小时）。结算窗口每月只有 8、9 号，
    #: 设计师可能过一阵才登录，所以给得比平台令牌宽松些。
    jwt_expire_hours: int = 72

    # 应用
    app_env: str = "dev"
    app_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # 实战话术录音目录；留空则用默认 backend/audio/live
    live_audio_dir: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
