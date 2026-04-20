from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError
from app.core.security import Actor
from app.domain.enums import UsageEventType
from app.models.project import Project
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.admin import AdminMetricsRead, AdminUserRead, FeatureFlagList, FeatureFlagRead
from app.services.usage_service import UsageService


class AdminService:
    def __init__(self, *, session: Session, actor: Actor) -> None:
        self.session = session
        self.actor = actor
        self.usage_service = UsageService(session=session, actor=actor)

    def assert_admin(self) -> None:
        if "admin" in self.actor.entitlements:
            return
        user = self.session.scalar(select(User).where(User.email == self.actor.email))
        if user is not None and user.role == "admin":
            return
        raise AuthorizationError("Admin access is required.")

    def list_users(self) -> list[AdminUserRead]:
        self.assert_admin()
        users = list(self.session.scalars(select(User).order_by(User.created_at.desc())))
        return [
            AdminUserRead(
                id=user.id,
                email=user.email,
                name=user.name,
                role=user.role,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
            for user in users
        ]

    def metrics(self) -> AdminMetricsRead:
        self.assert_admin()
        return AdminMetricsRead(
            user_count=int(self.session.scalar(select(func.count()).select_from(User)) or 0),
            project_count=int(self.session.scalar(select(func.count()).select_from(Project)) or 0),
            graph_count=int(self.session.scalar(select(func.count()).select_from(Workspace)) or 0),
            upload_count=self.usage_service.count_by_type(UsageEventType.UPLOAD),
            scrape_count=self.usage_service.count_by_type(UsageEventType.SCRAPE),
            ai_edit_count=self.usage_service.count_by_type(UsageEventType.AI_EDIT),
            export_count=self.usage_service.count_by_type(UsageEventType.EXPORT),
        )

    def flags(self) -> FeatureFlagList:
        self.assert_admin()
        return FeatureFlagList(
            items=[
                FeatureFlagRead(
                    key="export.custom_branding",
                    enabled=True,
                    description="Allow export theme overrides and brand metadata.",
                ),
                FeatureFlagRead(
                    key="ingestion.web_enrichment",
                    enabled=True,
                    description="Enable contextual web enrichment during ingestion.",
                ),
                FeatureFlagRead(
                    key="payments.midtrans",
                    enabled=True,
                    description="Enable Midtrans checkout and webhook handling.",
                ),
            ]
        )
