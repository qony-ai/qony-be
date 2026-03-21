from enum import IntEnum, StrEnum


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


class NodeRank(IntEnum):
    PROBLEM_STATEMENT = 1
    SUB_PROBLEM = 2
    HYPOTHESIS = 3
    FRAMEWORK_ANALYSIS = 4
    SUPPORTING_DATA = 5
    SYNTHESIS = 6

    @property
    def kind(self) -> str:
        return {
            NodeRank.PROBLEM_STATEMENT: "problem_statement",
            NodeRank.SUB_PROBLEM: "sub_problem",
            NodeRank.HYPOTHESIS: "hypothesis",
            NodeRank.FRAMEWORK_ANALYSIS: "framework_analysis",
            NodeRank.SUPPORTING_DATA: "supporting_evidence",
            NodeRank.SYNTHESIS: "synthesis",
        }[self]


class NodeSource(StrEnum):
    MANUAL = "manual"
    INGEST = "ingest"
    AI = "ai"


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
