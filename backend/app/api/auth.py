from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime
from app.core.config import settings
from app.core.security import create_access_token, verify_password, get_password_hash
from app.core.deps import get_db, get_current_active_user
from app.models.user import User, Tenant
from app.schemas.user import Token, UserOut, UserCreate

router = APIRouter()

@router.post("/login", response_model=Token, summary="用户登录")
def login(
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """用户名密码登录，返回 JWT Token"""
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="用户已被禁用")

    # 更新最后登录时间
    user.last_login = datetime.utcnow()
    db.commit()

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(subject=user.id, expires_delta=access_token_expires)
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserOut.model_validate(user)
    )

@router.post("/register", response_model=UserOut, summary="用户注册")
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    """注册新用户（仅在系统允许开放注册时可用）"""
    if not settings.ALLOW_REGISTRATION:
        raise HTTPException(status_code=403, detail="系统未开放注册，请联系管理员创建账号")

    existing = db.query(User).filter(User.username == user_in.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 获取默认租户
    tenant = db.query(Tenant).filter(Tenant.name == "默认租户").first()

    user = User(
        username=user_in.username,
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        is_active=True,
        is_superuser=False,
        tenant_id=tenant.id if tenant else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.get("/me", response_model=UserOut, summary="获取当前用户信息")
def read_current_user(current_user: User = Depends(get_current_active_user)):
    return current_user
