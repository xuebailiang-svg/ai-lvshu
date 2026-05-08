from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base_class import Base

class Tenant(Base):
    """租户表 - 支持多租户隔离"""
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, comment="租户名称")
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    users = relationship("User", back_populates="tenant")


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False, comment="用户名")
    email = Column(String(100), unique=True, index=True, nullable=True, comment="邮箱")
    hashed_password = Column(String(200), nullable=False)
    full_name = Column(String(100), nullable=True, comment="姓名")
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False, comment="是否超级管理员")
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, comment="所属租户")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    tenant = relationship("Tenant", back_populates="users")
