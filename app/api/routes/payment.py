from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_payment_service
from app.schemas.common import ApiEnvelope
from app.schemas.payment import CheckoutRequest, CheckoutResponse, MidtransWebhookResponse, SubscriptionRead
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payment", tags=["payment"])


@router.post("/checkout", response_model=ApiEnvelope[CheckoutResponse])
async def checkout(
    payload: CheckoutRequest,
    service: PaymentService = Depends(get_payment_service),
) -> ApiEnvelope[CheckoutResponse]:
    return ApiEnvelope(data=service.create_checkout(payload))


@router.post("/webhook/midtrans", response_model=ApiEnvelope[MidtransWebhookResponse])
async def midtrans_webhook(
    request: Request,
    service: PaymentService = Depends(get_payment_service),
) -> ApiEnvelope[MidtransWebhookResponse]:
    body = await request.json()
    return ApiEnvelope(data=service.handle_midtrans_webhook(body))


@router.get("/subscription", response_model=ApiEnvelope[SubscriptionRead | None])
async def get_active_subscription(
    service: PaymentService = Depends(get_payment_service),
) -> ApiEnvelope[SubscriptionRead | None]:
    subscription = service.get_active_subscription_for_actor()
    return ApiEnvelope(data=subscription)
