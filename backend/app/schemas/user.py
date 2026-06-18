from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = True

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None

class AdminUserCreate(UserBase):
    password: str
    is_superuser: bool = False
    is_active: bool = True

class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None

class PasswordReset(BaseModel):
    password: str

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

class UserOut(UserBase):
    id: int
    is_superuser: bool
    tenant_id: Optional[int] = None
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserOut

class TokenPayload(BaseModel):
    sub: Optional[str] = None
