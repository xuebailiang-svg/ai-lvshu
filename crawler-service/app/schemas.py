from typing import Literal
from pydantic import BaseModel, Field, HttpUrl


SourceType = Literal["official", "property", "government"]
SiteKey = Literal["baidu", "bing", "official", "58", "anjuke", "fang", "gov"]


class JobCreate(BaseModel):
    evaluation_id: int
    attempt: int = Field(default=0, ge=0, le=20)
    address: str = Field(min_length=2, max_length=500)
    city: str = Field(default="", max_length=100)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    sources: list[SourceType] = Field(default_factory=lambda: ["official", "property", "government"])
    sites: list[SiteKey] = Field(default_factory=lambda: ["baidu", "bing", "official", "58", "anjuke", "fang", "gov"])
    seed_urls: list[HttpUrl] = Field(default_factory=list, max_length=20)
    max_pages: int = Field(default=20, ge=1, le=20)
    timeout_seconds: int = Field(default=300, ge=30, le=300)


class JobCreated(BaseModel):
    job_id: str
    status: str
