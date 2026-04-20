from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class CheckoutRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=64)
    amount: int = Field(gt=0)
    currency: str = Field(default="IDR", min_length=3, max_length=3)
    customer_email: EmailStr
    customer_name: str = Field(min_length=1, max_length=255)


class CheckoutResponse(BaseModel):
    order_id: str
    snap_token: str | None = None
    redirect_url: str | None = None
    provider: str = "midtrans"


class SubscriptionRead(BaseModel):
    id: UUID
    user_id: UUID
    provider: str
    plan_id: str
    status: str
    order_id: str | None = None
    current_period_end: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class MidtransWebhookResponse(BaseModel):
    processed: bool = True
    order_id: str
    status: str
