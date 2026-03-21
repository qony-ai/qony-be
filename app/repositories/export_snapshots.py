from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.export_snapshot import ExportSnapshot


class ExportSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_snapshot(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        requested_by_user_id: UUID | None,
        branch_count: int,
        output_json: dict,
        status: str = "completed",
    ) -> ExportSnapshot:
        snapshot = ExportSnapshot(
            project_id=project_id,
            workspace_id=workspace_id,
            requested_by_user_id=requested_by_user_id,
            branch_count=branch_count,
            output_json=output_json,
            status=status,
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot
