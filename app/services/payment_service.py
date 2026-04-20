from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import os
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import DomainValidationError, NotFoundError
from app.core.security import Actor
from app.domain.enums import SubscriptionStatus
from app.models.subscription import Subscription
from app.repositories.users import UserRepository
from app.schemas.payment import CheckoutRequest, CheckoutResponse, MidtransWebhookResponse, SubscriptionRead


class PaymentService:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.user_repository = UserRepository(session)

    def create_checkout(self, payload: CheckoutRequest) -> CheckoutResponse:
        user = self.user_repository.get_or_create(
            email=self.actor.email,
            name=self.actor.name,
            external_auth_id=self.actor.auth_user_id,
        )
        order_id = f"qony-{payload.plan_id}-{int(datetime.now(UTC).timestamp())}"
        subscription = Subscription(
            user_id=user.id,
            provider="midtrans",
            plan_id=payload.plan_id,
            status=SubscriptionStatus.PENDING.value,
            order_id=order_id,
            metadata_json={"amount": payload.amount, "currency": payload.currency},
        )
        self.session.add(subscription)
        self.session.flush()

        snap_token = None
        redirect_url = None
        try:
            import midtransclient

            server_key = os.getenv("MIDTRANS_SERVER_KEY")
            if server_key:
                snap = midtransclient.Snap(
                    is_production=os.getenv("MIDTRANS_IS_PRODUCTION", "false") == "true",
                    server_key=server_key,
                )
                response = snap.create_transaction(
                    {
                        "transaction_details": {
                            "order_id": order_id,
                            "gross_amount": payload.amount,
                        },
                        "customer_details": {
                            "email": payload.customer_email,
                            "first_name": payload.customer_name,
                        },
                    }
                )
                snap_token = response.get("token")
                redirect_url = response.get("redirect_url")
        except Exception:
            snap_token = f"mock-snap-{order_id}"
            redirect_url = f"/billing/pending?order_id={order_id}"

        if snap_token is None:
            snap_token = f"mock-snap-{order_id}"
        if redirect_url is None:
            redirect_url = f"/billing/pending?order_id={order_id}"

        self.session.commit()
        return CheckoutResponse(
            order_id=order_id,
            snap_token=snap_token,
            redirect_url=redirect_url,
        )

    def handle_midtrans_webhook(self, body: dict) -> MidtransWebhookResponse:
        order_id = str(body.get("order_id", ""))
        status_code = str(body.get("status_code", ""))
        gross_amount = str(body.get("gross_amount", ""))
        provided_signature = str(body.get("signature_key", ""))
        server_key = os.getenv("MIDTRANS_SERVER_KEY", "")

        raw_sig = order_id + status_code + gross_amount + server_key
        expected = hashlib.sha512(raw_sig.encode()).hexdigest()
        if provided_signature != expected:
            raise DomainValidationError("Invalid signature")

        statement = select(Subscription).where(Subscription.order_id == order_id)
        subscription = self.session.scalar(statement)
        if subscription is None:
            raise NotFoundError("Subscription order not found.")

        transaction_status = str(body.get("transaction_status", ""))
        if transaction_status == "settlement":
            subscription.status = SubscriptionStatus.ACTIVE.value
            subscription.current_period_end = datetime.now(UTC) + timedelta(days=30)
        elif transaction_status in {"expire", "cancel"}:
            subscription.status = SubscriptionStatus.EXPIRED.value if transaction_status == "expire" else SubscriptionStatus.CANCELED.value
        elif transaction_status == "deny":
            subscription.status = SubscriptionStatus.DENIED.value

        subscription.metadata_json = {
            **(subscription.metadata_json or {}),
            "last_webhook": body,
        }
        self.session.commit()
        return MidtransWebhookResponse(processed=True, order_id=order_id, status=subscription.status)

    def get_active_subscription(self, user_id: UUID) -> SubscriptionRead | None:
        statement = (
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.updated_at.desc())
        )
        subscription = self.session.scalars(statement).first()
        if subscription is None:
            return None
        return SubscriptionRead(
            id=subscription.id,
            user_id=subscription.user_id,
            provider=subscription.provider,
            plan_id=subscription.plan_id,
            status=subscription.status,
            order_id=subscription.order_id,
            current_period_end=subscription.current_period_end,
            metadata=subscription.metadata_json or {},
        )

    def get_active_subscription_for_actor(self) -> SubscriptionRead | None:
        user = self.user_repository.get_or_create(
            email=self.actor.email,
            name=self.actor.name,
            external_auth_id=self.actor.auth_user_id,
        )
        return self.get_active_subscription(user.id)
