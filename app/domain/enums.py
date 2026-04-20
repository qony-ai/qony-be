from enum import StrEnum


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class IngestJobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeNodeType(StrEnum):
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


class KnowledgeRelationType(StrEnum):
    CAUSES = "causes"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    REQUIRES = "requires"
    AFFECTS = "affects"
    RELATED_TO = "related_to"
    MEASURED_BY = "measured_by"
    MITIGATED_BY = "mitigated_by"


class KnowledgeNodeSource(StrEnum):
    DOCUMENT = "document"
    WEB = "web"
    USER = "user"


class ExportType(StrEnum):
    PITCH_DECK = "pitch_deck"
    BUSINESS_DOCUMENT = "business_document"


class ExportJobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SubscriptionStatus(StrEnum):
    FREE = "free"
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELED = "canceled"
    DENIED = "denied"


class UsageEventType(StrEnum):
    UPLOAD = "upload"
    SCRAPE = "scrape"
    AI_EDIT = "ai_edit"
    EXPORT = "export"
