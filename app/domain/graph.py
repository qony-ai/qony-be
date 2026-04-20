from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from app.core.exceptions import DomainValidationError
from app.domain.enums import NodeSource
from app.schemas.workspace import (
    GraphValidationIssue,
    GraphValidationSummary,
    WorkspaceGraph,
)


def validate_graph(graph: WorkspaceGraph) -> GraphValidationSummary:
    """Validate a flat typed workspace graph.

    Hard constraints enforced here:
    - unique node ids
    - unique edge ids
    - edges must reference existing nodes (no dangling endpoints)
    - no self-loops (source != target)
    - unique (source, target) pair per workspace
    - web-source nodes must have is_enrichment=true and source_url set
      (Pydantic validators already enforce this, re-checked here for safety)

    Cycles are intentionally NOT enforced: business case graphs legitimately
    contain feedback loops (e.g., Risk -mitigated_by-> Solution -causes-> Risk).
    AI prompts are responsible for avoiding nonsensical loops; the UI may warn
    but does not block.
    """
    issues: list[GraphValidationIssue] = []
    nodes_by_id: dict[UUID, object] = {}
    edges_by_id: set[UUID] = set()
    edge_pairs: set[tuple[UUID, UUID]] = set()
    adjacency: dict[UUID, list[UUID]] = defaultdict(list)
    reverse_adjacency: dict[UUID, list[UUID]] = defaultdict(list)

    for node in graph.nodes:
        if node.id in nodes_by_id:
            issues.append(
                GraphValidationIssue(
                    code="duplicate_node_id",
                    message=f"Duplicate node id detected: {node.id}",
                    node_id=node.id,
                )
            )
            continue
        nodes_by_id[node.id] = node

        if node.source == NodeSource.WEB:
            if not node.is_enrichment or not node.source_url:
                issues.append(
                    GraphValidationIssue(
                        code="web_node_missing_enrichment_metadata",
                        message=(
                            "Nodes with source='web' must have is_enrichment=true "
                            "and a non-empty source_url."
                        ),
                        node_id=node.id,
                    )
                )
        elif node.is_enrichment:
            issues.append(
                GraphValidationIssue(
                    code="non_web_node_marked_enrichment",
                    message="is_enrichment=true is only valid when source='web'.",
                    node_id=node.id,
                )
            )

    for edge in graph.edges:
        if edge.id in edges_by_id:
            issues.append(
                GraphValidationIssue(
                    code="duplicate_edge_id",
                    message=f"Duplicate edge id detected: {edge.id}",
                    edge_id=edge.id,
                )
            )
            continue
        edges_by_id.add(edge.id)

        if edge.source not in nodes_by_id or edge.target not in nodes_by_id:
            issues.append(
                GraphValidationIssue(
                    code="edge_missing_endpoint",
                    message="Edge references a node that does not exist.",
                    edge_id=edge.id,
                )
            )
            continue

        if edge.source == edge.target:
            issues.append(
                GraphValidationIssue(
                    code="self_loop",
                    message="Self-referential edges are not allowed.",
                    edge_id=edge.id,
                )
            )
            continue

        pair = (edge.source, edge.target)
        if pair in edge_pairs:
            issues.append(
                GraphValidationIssue(
                    code="duplicate_edge_pair",
                    message="An edge already connects this source to this target.",
                    edge_id=edge.id,
                )
            )
            continue
        edge_pairs.add(pair)

        adjacency[edge.source].append(edge.target)
        reverse_adjacency[edge.target].append(edge.source)

    reachable_node_count = sum(
        1
        for node_id in nodes_by_id
        if adjacency.get(node_id) or reverse_adjacency.get(node_id)
    )

    return GraphValidationSummary(
        is_valid=not issues,
        issues=issues,
        reachable_node_count=reachable_node_count,
        complete_branch_count=0,
    )


def ensure_valid_graph(graph: WorkspaceGraph) -> GraphValidationSummary:
    summary = validate_graph(graph)
    if not summary.is_valid:
        raise DomainValidationError(
            "Workspace graph validation failed.",
            details={"issues": [issue.model_dump(mode="json") for issue in summary.issues]},
        )
    return summary
