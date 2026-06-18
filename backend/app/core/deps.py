from typing import Generator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import ALGORITHM
from app.db.session import SessionLocal
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def get_db() -> Generator:
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()


def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    try:
        user_pk = int(user_id)
    except (TypeError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_pk).first()
    if user is None:
        raise credentials_exception
    return user


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="User is disabled")
    return current_user


def get_current_superuser(current_user: User = Depends(get_current_active_user)) -> User:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Permission denied: administrator required")
    return current_user


def require_superuser(current_user: User = Depends(get_current_active_user)) -> User:
    return get_current_superuser(current_user)


def get_current_tenant_id(current_user: User) -> int:
    return current_user.tenant_id or 1


def can_delete_owned_or_admin(record_owner_id: Optional[int], current_user: User) -> bool:
    return bool(current_user.is_superuser or (record_owner_id is not None and record_owner_id == current_user.id))


def ensure_owned_or_admin(
    record_owner_id: Optional[int],
    current_user: User,
    action: str = "operate on",
) -> None:
    if not can_delete_owned_or_admin(record_owner_id, current_user):
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: you can only {action} records you created",
        )
