from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from uuid import UUID

from app.core.exceptions import DomainValidationError
from app.domain.enums import NodeRank
from app.schemas.workspace import (
    GraphEdge,
    GraphNode,
    GraphValidationIssue,
    GraphValidationSummary,
    WorkspaceGraph,
)

ALLOWED_TRANSITIONS: dict[NodeRank, NodeRank] = {
    NodeRank.PROBLEM_STATEMENT: NodeRank.SUB_PROBLEM,
    NodeRank.SUB_PROBLEM: NodeRank.HYPOTHESIS,
    NodeRank.HYPOTHESIS: NodeRank.FRAMEWORK_ANALYSIS,
    NodeRank.FRAMEWORK_ANALYSIS: NodeRank.SUPPORTING_DATA,
    NodeRank.SUPPORTING_DATA: NodeRank.SYNTHESIS,
}


def validate_graph(graph: WorkspaceGraph) -> GraphValidationSummary:
    issues: list[GraphValidationIssue] = []
    nodes_by_id: dict[UUID, GraphNode] = {}
    edges_by_id: set[UUID] = set()
    adjacency: dict[UUID, list[UUID]] = defaultdict(list)
    reverse_adjacency: dict[UUID, list[UUID]] = defaultdict(list)
    edge_pairs: set[tuple[UUID, UUID]] = set()

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
                    message="Duplicate source to target edge detected.",
                    edge_id=edge.id,
                )
            )
            continue
        edge_pairs.add(pair)

        source_rank = nodes_by_id[edge.source].rank
        target_rank = nodes_by_id[edge.target].rank

        if target_rank <= source_rank:
            issues.append(
                GraphValidationIssue(
                    code="reverse_logic_flow",
                    message="Edges must point from lower ranks to higher ranks.",
                    edge_id=edge.id,
                )
            )
            continue

        if ALLOWED_TRANSITIONS.get(source_rank) != target_rank:
            issues.append(
                GraphValidationIssue(
                    code="invalid_rank_transition",
                    message=(
                        f"Edge {edge.id} violates allowed rank transitions: "
                        f"{source_rank.value}->{target_rank.value}"
                    ),
                    edge_id=edge.id,
                )
            )
            continue

        adjacency[edge.source].append(edge.target)
        reverse_adjacency[edge.target].append(edge.source)

    rank_one_nodes = [node.id for node in graph.nodes if node.rank == NodeRank.PROBLEM_STATEMENT]
    if graph.nodes and not rank_one_nodes:
        issues.append(
            GraphValidationIssue(
                code="missing_rank_one_root",
                message="A non-empty graph must contain exactly one Rank 1 problem statement.",
            )
        )
    if len(rank_one_nodes) > 1:
        issues.append(
            GraphValidationIssue(
                code="multiple_rank_one_roots",
                message="Only one Rank 1 problem statement is allowed per workspace.",
            )
        )

    for node in graph.nodes:
        parents = reverse_adjacency.get(node.id, [])
        children = adjacency.get(node.id, [])

        if node.rank == NodeRank.PROBLEM_STATEMENT and parents:
            issues.append(
                GraphValidationIssue(
                    code="rank_one_has_parent",
                    message="Rank 1 nodes cannot have incoming edges.",
                    node_id=node.id,
                )
            )

        if node.rank != NodeRank.PROBLEM_STATEMENT and not parents:
            issues.append(
                GraphValidationIssue(
                    code="unreachable_or_orphaned_node",
                    message="Non-root nodes must be connected to an upstream branch.",
                    node_id=node.id,
                )
            )

        if node.rank == NodeRank.FRAMEWORK_ANALYSIS and not any(
            nodes_by_id[parent_id].rank == NodeRank.HYPOTHESIS for parent_id in parents
        ):
            issues.append(
                GraphValidationIssue(
                    code="rank_four_requires_rank_three_parent",
                    message="Rank 4 nodes require at least one Rank 3 parent.",
                    node_id=node.id,
                )
            )

        if node.rank == NodeRank.SYNTHESIS and children:
            issues.append(
                GraphValidationIssue(
                    code="rank_six_must_be_leaf",
                    message="Rank 6 synthesis nodes must be leaf nodes.",
                    node_id=node.id,
                )
            )

    if _contains_cycle(nodes_by_id.keys(), adjacency):
        issues.append(
            GraphValidationIssue(
                code="cycle_detected",
                message="Workspace graph must remain acyclic.",
            )
        )

    reachable_nodes: set[UUID] = set()
    if len(rank_one_nodes) == 1:
        reachable_nodes = _collect_reachable(rank_one_nodes[0], adjacency)
        for node in graph.nodes:
            if node.id not in reachable_nodes:
                issues.append(
                    GraphValidationIssue(
                        code="node_not_traceable_to_rank_one",
                        message="Every node must be traceable to the Rank 1 problem statement.",
                        node_id=node.id,
                    )
                )

    for node in graph.nodes:
        if node.rank == NodeRank.SYNTHESIS and node.id not in reachable_nodes and graph.nodes:
            issues.append(
                GraphValidationIssue(
                    code="orphan_synthesis_branch",
                    message="Rank 6 synthesis nodes must remain reachable from Rank 1.",
                    node_id=node.id,
                )
            )

    complete_branch_count = 0
    if len(rank_one_nodes) == 1 and not any(issue.code == "cycle_detected" for issue in issues):
        complete_branch_count = _count_complete_branches(
            rank_one_nodes[0],
            adjacency,
            nodes_by_id,
        )

    return GraphValidationSummary(
        is_valid=not issues,
        issues=issues,
        reachable_node_count=len(reachable_nodes),
        complete_branch_count=complete_branch_count,
    )


def ensure_valid_graph(graph: WorkspaceGraph) -> GraphValidationSummary:
    summary = validate_graph(graph)
    if not summary.is_valid:
        raise DomainValidationError(
            "Workspace graph validation failed.",
            details={"issues": [issue.model_dump(mode="json") for issue in summary.issues]},
        )
    return summary


def collect_complete_paths(graph: WorkspaceGraph, *, path_limit: int = 250) -> tuple[list[list[GraphNode]], bool]:
    ensure_valid_graph(graph)
    if not graph.nodes:
        return [], False

    nodes_by_id: dict[UUID, GraphNode] = {node.id: node for node in graph.nodes}
    adjacency: dict[UUID, list[UUID]] = defaultdict(list)
    for edge in graph.edges:
        adjacency[edge.source].append(edge.target)

    roots = [node.id for node in graph.nodes if node.rank == NodeRank.PROBLEM_STATEMENT]
    if len(roots) != 1:
        raise DomainValidationError("Export preview requires exactly one Rank 1 root node.")

    root_id = roots[0]
    paths: list[list[GraphNode]] = []
    truncated = False

    def walk(node_id: UUID, trail: list[GraphNode]) -> None:
        nonlocal truncated
        if truncated:
            return
        node = nodes_by_id[node_id]
        next_trail = [*trail, node]
        if node.rank == NodeRank.SYNTHESIS:
            paths.append(next_trail)
            if len(paths) >= path_limit:
                truncated = True
            return

        children = sorted(
            adjacency.get(node_id, []),
            key=lambda child_id: (
                nodes_by_id[child_id].rank,
                nodes_by_id[child_id].title.lower(),
                str(child_id),
            ),
        )
        for child_id in children:
            walk(child_id, next_trail)

    walk(root_id, [])
    return paths, truncated


def _contains_cycle(node_ids: Iterable[UUID], adjacency: dict[UUID, list[UUID]]) -> bool:
    in_degree: dict[UUID, int] = {node_id: 0 for node_id in node_ids}
    for source, children in adjacency.items():
        in_degree.setdefault(source, 0)
        for child in children:
            in_degree[child] = in_degree.get(child, 0) + 1

    queue = deque([node_id for node_id, degree in in_degree.items() if degree == 0])
    visited = 0
    while queue:
        node_id = queue.popleft()
        visited += 1
        for child in adjacency.get(node_id, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    return visited != len(in_degree)


def _collect_reachable(root_id: UUID, adjacency: dict[UUID, list[UUID]]) -> set[UUID]:
    stack = [root_id]
    reachable: set[UUID] = set()
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(reversed(adjacency.get(current, [])))
    return reachable


def _count_complete_branches(
    node_id: UUID,
    adjacency: dict[UUID, list[UUID]],
    nodes_by_id: dict[UUID, GraphNode],
) -> int:
    node = nodes_by_id[node_id]
    if node.rank == NodeRank.SYNTHESIS:
        return 1

    total = 0
    for child_id in adjacency.get(node_id, []):
        total += _count_complete_branches(child_id, adjacency, nodes_by_id)
    return total
