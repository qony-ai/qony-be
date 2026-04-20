from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AdminUserRead(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    created_at: datetime
    updated_at: datetime


class AdminMetricsRead(BaseModel):
    user_count: int = 0
    project_count: int = 0
    graph_count: int = 0
    upload_count: int = 0
    scrape_count: int = 0
    ai_edit_count: int = 0
    export_count: int = 0


class FeatureFlagRead(BaseModel):
    key: str
    enabled: bool
    description: str


class FeatureFlagList(BaseModel):
    items: list[FeatureFlagRead] = Field(default_factory=list)
