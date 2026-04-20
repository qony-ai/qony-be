from enum import StrEnum


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class IngestJobStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportSnapshotStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class AIRequestStatus(StrEnum):
    COMPLETED = "completed"
    FALLBACK = "fallback"
    FAILED = "failed"


class NodeType(StrEnum):
    PROBLEM = "problem"
    SOLUTION = "solution"
    ASSUMPTION = "assumption"
    METRIC = "metric"
    STAKEHOLDER = "stakeholder"
    RISK = "risk"
    OPPORTUNITY = "opportunity"
    CONSTRAINT = "constraint"
    EVIDENCE = "evidence"
    MARKET_DATA = "market_data"
    TREND = "trend"
    COMPETITOR = "competitor"
    REGULATION = "regulation"
    OBJECTIVE = "objective"
    RESOURCE = "resource"


class EdgeType(StrEnum):
    CAUSES = "causes"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    REQUIRES = "requires"
    AFFECTS = "affects"
    RELATED_TO = "related_to"
    MEASURED_BY = "measured_by"
    MITIGATED_BY = "mitigated_by"


class NodeSource(StrEnum):
    DOCUMENT = "document"
    WEB = "web"
    USER = "user"


class MutationCommandType(StrEnum):
    ADD_NODE = "add_node"
    UPDATE_NODE = "update_node"
    DELETE_NODE = "delete_node"
    ADD_EDGE = "add_edge"
    DELETE_EDGE = "delete_edge"
    MOVE_NODE = "move_node"
    APPLY_AI_PATCH = "apply_ai_patch"


class AIProviderKind(StrEnum):
    STUB = "stub"
    OLLAMA = "ollama"
    REMOTE = "remote"


class AIRequestOperation(StrEnum):
    INGEST = "ingest"
    WORKSPACE_MUTATION = "workspace_mutation"
    EXPORT_ASSIST = "export_assist"


