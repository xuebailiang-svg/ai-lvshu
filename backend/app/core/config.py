from typing import List, Optional, Union
from pydantic import AnyHttpUrl, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "电竞馆智能选址系统"
    API_V1_STR: str = "/api/v1"

    # CORS
    # 前后端默认同源部署，不需要跨域。确需跨域时通过环境变量显式配置可信域名。
    BACKEND_CORS_ORIGINS: List[str] = []

    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            origins = [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, (list, str)):
            origins = v
        else:
            raise ValueError(v)
        if "*" in origins:
            raise ValueError("BACKEND_CORS_ORIGINS must list explicit trusted origins; wildcard is not allowed")
        return origins

    # 数据库 —— 支持两种方式配置：
    # 方式 1：直接在 .env 中写 DATABASE_URL=postgresql://...
    # 方式 2：分别写 POSTGRES_SERVER / POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB
    DATABASE_URL: Optional[str] = None
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "esports_user"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "esports_db"

    # 最终使用的数据库 URI（优先使用 DATABASE_URL，否则自动组装）
    SQLALCHEMY_DATABASE_URI: Optional[str] = None

    @validator("SQLALCHEMY_DATABASE_URI", pre=True, always=True)
    def assemble_db_uri(cls, v, values):
        # 如果 .env 中直接写了 DATABASE_URL，优先使用
        if values.get("DATABASE_URL"):
            return values["DATABASE_URL"]
        # 否则从分散字段组装
        user = values.get("POSTGRES_USER", "esports_user")
        password = values.get("POSTGRES_PASSWORD", "")
        if not password:
            raise ValueError("DATABASE_URL or POSTGRES_PASSWORD must be configured")
        server = values.get("POSTGRES_SERVER", "localhost")
        db = values.get("POSTGRES_DB", "esports_db")
        return f"postgresql://{user}:{password}@{server}/{db}"

    # Security
    # 必须由部署环境提供，禁止使用仓库内固定密钥。
    SECRET_KEY: str
    INITIAL_ADMIN_PASSWORD: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 天
    ALLOW_REGISTRATION: bool = False

    @validator("SECRET_KEY")
    def validate_secret_key(cls, value: str) -> str:
        if len(value) < 32 or value.startswith(("CHANGE_ME", "replace_")):
            raise ValueError("SECRET_KEY must be a random value of at least 32 characters")
        return value

    class Config:
        case_sensitive = True
        env_file = ".env"


settings = Settings()
