from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    internal_token: str = ""
    redis_url: str = "redis://127.0.0.1:6379/2"
    temp_dir: str = "/tmp/esports-crawler"
    max_pages: int = 20
    task_timeout_seconds: int = 300
    domain_delay_seconds: float = 3.0
    max_response_bytes: int = 5 * 1024 * 1024

    class Config:
        env_file = ".env"
        env_prefix = "CRAWLER_"

    def ensure_dirs(self) -> None:
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
