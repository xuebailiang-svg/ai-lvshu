from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_active_user, get_current_superuser, get_current_tenant_id, get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import Tenant, User
from app.schemas.user import (
    AdminUserCreate,
    AdminUserUpdate,
    PasswordChange,
    PasswordReset,
    Token,
    UserCreate,
    UserOut,
)

router = APIRouter()


def _default_tenant(db: Session) -> Tenant | None:
    return db.query(Tenant).filter(Tenant.name == "默认租户").first() or db.query(Tenant).first()


def _get_user_in_tenant(db: Session, user_id: int, tenant_id: int) -> User:
    user = db.query(User).filter(User.id == user_id, User.tenant_id == tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


def _validate_password(password: str) -> None:
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")


def _ensure_unique_user(db: Session, username: str | None, email: str | None, exclude_id: int | None = None) -> None:
    if username:
        query = db.query(User).filter(User.username == username)
        if exclude_id:
            query = query.filter(User.id != exclude_id)
        if query.first():
            raise HTTPException(status_code=400, detail="用户名已存在")
    if email:
        query = db.query(User).filter(User.email == email)
        if exclude_id:
            query = query.filter(User.id != exclude_id)
        if query.first():
            raise HTTPException(status_code=400, detail="邮箱已存在")


@router.post("/login", response_model=Token, summary="用户登录")
def login(
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="用户已被禁用")

    user.last_login = datetime.utcnow()
    db.commit()

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(subject=user.id, expires_delta=access_token_expires)
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=UserOut, summary="用户注册")
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    if not settings.ALLOW_REGISTRATION:
        raise HTTPException(status_code=403, detail="系统未开放注册，请联系管理员创建账号")

    _validate_password(user_in.password)
    _ensure_unique_user(db, user_in.username, user_in.email)
    tenant = _default_tenant(db)

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


@router.put("/me/password", summary="当前用户修改自己的密码")
def change_my_password(
    req: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not verify_password(req.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")
    _validate_password(req.new_password)
    current_user.hashed_password = get_password_hash(req.new_password)
    db.commit()
    return {"message": "密码已更新"}


@router.get("/users", response_model=list[UserOut], summary="管理员查看当前租户用户")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    tenant_id = get_current_tenant_id(current_user)
    return db.query(User).filter(User.tenant_id == tenant_id).order_by(User.created_at.desc()).all()


@router.post("/users", response_model=UserOut, summary="管理员创建用户")
def create_user(
    user_in: AdminUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    username = user_in.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    _validate_password(user_in.password)
    _ensure_unique_user(db, username, user_in.email)
    user = User(
        username=username,
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        is_active=bool(user_in.is_active),
        is_superuser=bool(user_in.is_superuser),
        tenant_id=get_current_tenant_id(current_user),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserOut, summary="管理员修改用户")
def update_user(
    user_id: int,
    user_in: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    tenant_id = get_current_tenant_id(current_user)
    user = _get_user_in_tenant(db, user_id, tenant_id)
    if user.id == current_user.id:
        if user_in.is_active is False:
            raise HTTPException(status_code=400, detail="不能禁用自己的管理员账号")
        if user_in.is_superuser is False:
            raise HTTPException(status_code=400, detail="不能把自己的管理员账号降级为普通用户")

    if user_in.email is not None and user_in.email != user.email:
        _ensure_unique_user(db, None, user_in.email, exclude_id=user.id)
        user.email = user_in.email
    if user_in.full_name is not None:
        user.full_name = user_in.full_name
    if user_in.is_active is not None:
        user.is_active = bool(user_in.is_active)
    if user_in.is_superuser is not None:
        user.is_superuser = bool(user_in.is_superuser)
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/reset-password", summary="管理员重置用户密码")
def reset_user_password(
    user_id: int,
    req: PasswordReset,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    _validate_password(req.password)
    user = _get_user_in_tenant(db, user_id, get_current_tenant_id(current_user))
    user.hashed_password = get_password_hash(req.password)
    db.commit()
    return {"message": "密码已重置"}
