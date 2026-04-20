from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=255)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=4096)


class AuthUserRead(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    role: str
    created_at: datetime
    updated_at: datetime


class AuthTokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthResponse(BaseModel):
    user: AuthUserRead
    tokens: AuthTokens
