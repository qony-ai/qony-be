"""Deterministic ingest for flat typed workspace graphs.

Turns a raw document into a minimal flat graph of typed nodes (problem,
evidence, solution, etc.) connected by typed edges (causes, supports,
affects, ...). This is the fallback used when ``AI_PROVIDER=stub`` or when
a real provider fails and the app is configured to fall back.

No rank, no hierarchy: relationships live on ``edge.type``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.enums import EdgeType, NodeSource, NodeType
from app.schemas.workspace import (
    GraphEdge,
    GraphMetadata,
    GraphNode,
    GraphValidationSummary,
    Position,
    WorkspaceGraph,
)

SECTION_RE = re.compile(r"^(?P<prefix>\d+(?:\.\d+)*[\.\)])\s*(?P<title>.+)$")
PAGE_MARKER_RE = re.compile(r"^(dokumen .* halaman \d+|halaman \d+|page \d+)$", re.IGNORECASE)
BULLET_RE = re.compile(r"^[\-\*\u2022\u25cf\u25aa]\s*(.+)$")
METRIC_RE = re.compile(r"(\d+(?:[.,]\d+)?%|Rp\s?\d[\d.,]*|USD\s?\d[\d.,]*|\$\s?\d[\d.,]*)")

PROBLEM_KEYWORDS = (
    "masalah", "problem", "tantangan", "challenge", "pain point",
    "bottleneck", "delay", "lambat", "kurang", "gagal", "inefficient",
)
SOLUTION_KEYWORDS = (
    "rekomendasi", "recommend", "solution", "solusi", "implementasi",
    "rollout", "kesimpulan", "proposed", "initiative",
)
EVIDENCE_KEYWORDS = (
    "payback", "roi", "bulan", "month", "quarter", "q1", "q2", "q3", "q4",
    "investasi", "budget", "benefit", "impact", "savings",
)
RISK_KEYWORDS = ("risk", "risiko", "ancaman", "threat")
OPPORTUNITY_KEYWORDS = ("opportunity", "peluang", "kesempatan")

HORIZONTAL_SPACING = 340.0
VERTICAL_SPACING = 200.0


@dataclass(frozen=True, slots=True)
class Section:
    heading: str
    lines: tuple[str, ...]


def build_deterministic_ingest_graph(
    *,
    project_id: UUID,
    workspace_id: UUID,
    workspace_version: int,
    raw_text: str,
    created_at: datetime,
    ingest_mode: str = "stub",
    provider_attempted: str | None = None,
) -> WorkspaceGraph:
    lines = _clean_lines(raw_text)
    sections = _extract_sections(lines)

    problem_title = _pick_document_title(lines, sections)
    problem_description = _clip_content(
        " ".join(lines[:6]) if lines else problem_title,
        max_chars=1000,
    )

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    problem_id = uuid4()
    nodes.append(
        _make_node(
            node_id=problem_id,
            node_type=NodeType.PROBLEM,
            title=_clip_title(problem_title, 255),
            description=problem_description or problem_title,
            position=Position(x=0.0, y=0.0),
            created_at=created_at,
        )
    )

    supporting: list[tuple[NodeType, EdgeType, Section]] = []
    for section in sections:
        classification = _classify_section(section)
        if classification is not None:
            supporting.append((classification[0], classification[1], section))

    supporting = supporting[:6]

    for index, (node_type, edge_type, section) in enumerate(supporting, start=1):
        node_id = uuid4()
        title = _clip_title(section.heading, 255)
        description = _clip_content(" ".join(section.lines) or section.heading, 1000)
        nodes.append(
            _make_node(
                node_id=node_id,
                node_type=node_type,
                title=title,
                description=description,
                position=Position(
                    x=HORIZONTAL_SPACING,
                    y=(index - (len(supporting) + 1) / 2) * VERTICAL_SPACING,
                ),
                created_at=created_at,
            )
        )
        edges.append(
            _make_edge(
                source=node_id if edge_type in {EdgeType.SUPPORTS, EdgeType.CAUSES} else problem_id,
                target=problem_id if edge_type in {EdgeType.SUPPORTS, EdgeType.CAUSES} else node_id,
                edge_type=edge_type,
                created_at=created_at,
            )
        )

    metrics = _extract_metrics(lines)
    for index, metric in enumerate(metrics[:3], start=1):
        metric_id = uuid4()
        nodes.append(
            _make_node(
                node_id=metric_id,
                node_type=NodeType.METRIC,
                title=_clip_title(metric, 255),
                description=metric,
                position=Position(
                    x=-HORIZONTAL_SPACING,
                    y=index * VERTICAL_SPACING,
                ),
                created_at=created_at,
            )
        )
        edges.append(
            _make_edge(
                source=metric_id,
                target=problem_id,
                edge_type=EdgeType.MEASURED_BY,
                created_at=created_at,
            )
        )

    attributes: dict[str, object] = {
        "ingest_mode": ingest_mode,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
    if provider_attempted is not None:
        attributes["provider_attempted"] = provider_attempted

    return WorkspaceGraph(
        nodes=nodes,
        edges=edges,
        metadata=GraphMetadata(
            project_id=project_id,
            workspace_id=workspace_id,
            version=workspace_version,
            updated_at=created_at,
            validation=GraphValidationSummary(is_valid=True),
            attributes=attributes,
        ),
    )


# ---------------------------------------------------------------- parsing


def _clean_lines(raw_text: str) -> list[str]:
    out: list[str] = []
    for raw_line in raw_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if PAGE_MARKER_RE.match(line):
            continue
        out.append(line)
    return out


def _extract_sections(lines: list[str]) -> list[Section]:
    sections: list[Section] = []
    current_heading: str | None = None
    current_body: list[str] = []

    def flush() -> None:
        if current_heading is not None:
            sections.append(Section(heading=current_heading, lines=tuple(current_body)))

    for line in lines:
        match = SECTION_RE.match(line)
        if match:
            flush()
            current_heading = match.group("title").strip()
            current_body = []
            continue
        bullet = BULLET_RE.match(line)
        if bullet and current_heading is None:
            current_heading = bullet.group(1).strip()
            current_body = []
            continue
        if current_heading is None:
            continue
        current_body.append(line)

    flush()
    return sections


def _pick_document_title(lines: list[str], sections: list[Section]) -> str:
    for line in lines:
        if len(line) > 4 and line == line.title():
            return line
    for line in lines:
        if len(line) > 8:
            return line
    if sections:
        return sections[0].heading
    return "Business case"


def _classify_section(section: Section) -> tuple[NodeType, EdgeType] | None:
    body = " ".join([section.heading, *section.lines]).lower()
    if any(keyword in body for keyword in SOLUTION_KEYWORDS):
        return NodeType.SOLUTION, EdgeType.AFFECTS
    if any(keyword in body for keyword in EVIDENCE_KEYWORDS):
        return NodeType.EVIDENCE, EdgeType.SUPPORTS
    if any(keyword in body for keyword in RISK_KEYWORDS):
        return NodeType.RISK, EdgeType.AFFECTS
    if any(keyword in body for keyword in OPPORTUNITY_KEYWORDS):
        return NodeType.OPPORTUNITY, EdgeType.RELATED_TO
    if any(keyword in body for keyword in PROBLEM_KEYWORDS):
        return NodeType.PROBLEM, EdgeType.CAUSES
    return NodeType.ASSUMPTION, EdgeType.RELATED_TO


def _extract_metrics(lines: list[str]) -> list[str]:
    metrics: list[str] = []
    seen: set[str] = set()
    for line in lines:
        for match in METRIC_RE.finditer(line):
            value = match.group(0).strip()
            if value and value not in seen:
                seen.add(value)
                metrics.append(value)
    return metrics


# ---------------------------------------------------------- builders


def _make_node(
    *,
    node_id: UUID,
    node_type: NodeType,
    title: str,
    description: str,
    position: Position,
    created_at: datetime,
) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=node_type,
        title=title or "Untitled",
        description=description or title or "Untitled",
        source=NodeSource.DOCUMENT,
        is_enrichment=False,
        source_url=None,
        confidence=0.7,
        position=position,
        metadata={"generator": "deterministic_ingest"},
        created_at=created_at,
        updated_at=created_at,
    )


def _make_edge(
    *,
    source: UUID,
    target: UUID,
    edge_type: EdgeType,
    created_at: datetime,
) -> GraphEdge:
    return GraphEdge(
        id=uuid4(),
        type=edge_type,
        source=source,
        target=target,
        label=None,
        metadata={"generator": "deterministic_ingest"},
        created_at=created_at,
        updated_at=created_at,
    )


# ---------------------------------------------------------- utilities


def _clip_title(value: str, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return "Untitled"
    if len(cleaned) <= max_chars:
        return cleaned
    truncated = cleaned[: max_chars - 1].rsplit(" ", 1)[0].strip()
    return truncated or cleaned[: max_chars - 1]


def _clip_content(value: str, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    truncated = cleaned[: max_chars - 1].rsplit(" ", 1)[0].strip()
    return (truncated or cleaned[: max_chars - 1]) + "..."
