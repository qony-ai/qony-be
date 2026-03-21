from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from app.core.exceptions import DomainValidationError
from app.domain.enums import NodeRank
from app.domain.graph import ensure_valid_graph
from app.schemas.export import ExportChain, ExportStep
from app.schemas.workspace import GraphNode, WorkspaceGraph


def build_export_preview(
    graph: WorkspaceGraph,
    *,
    path_limit: int = 250,
) -> tuple[list[ExportChain], list[str]]:
    ensure_valid_graph(graph)
    warnings: list[str] = []

    if not graph.nodes:
        return [], warnings

    nodes_by_id: dict[UUID, GraphNode] = {node.id: node for node in graph.nodes}
    children_by_id: dict[UUID, list[UUID]] = defaultdict(list)
    for edge in sorted(graph.edges, key=lambda item: (str(item.source), str(item.target), str(item.id))):
        children_by_id[edge.source].append(edge.target)

    roots = [node.id for node in graph.nodes if node.rank == NodeRank.PROBLEM_STATEMENT]
    if len(roots) != 1:
        raise DomainValidationError("Export preview requires exactly one Rank 1 root node.")

    root_id = roots[0]
    chains: list[ExportChain] = []
    truncated = False

    def walk(node_id: UUID, path: list[GraphNode]) -> None:
        nonlocal truncated
        if truncated:
            return

        node = nodes_by_id[node_id]
        next_path = [*path, node]
        children = sorted(
            children_by_id.get(node_id, []),
            key=lambda child_id: (
                nodes_by_id[child_id].rank,
                nodes_by_id[child_id].title.lower(),
                str(child_id),
            ),
        )

        if node.rank == NodeRank.SYNTHESIS:
            chains.append(
                ExportChain(
                    chain_id=f"{root_id}:{len(chains) + 1}",
                    steps=[
                        ExportStep(
                            node_id=step.id,
                            rank=int(step.rank),
                            kind=step.kind,
                            title=step.title,
                            content=step.content,
                        )
                        for step in next_path
                    ],
                )
            )
            if len(chains) >= path_limit:
                truncated = True
            return

        if not children:
            return

        for child_id in children:
            walk(child_id, next_path)

    walk(root_id, [])

    if truncated:
        warnings.append(
            f"Export preview was truncated to the first {path_limit} complete branches."
        )

    return chains, warnings


def build_fallback_narrative(chains: list[ExportChain]) -> str | None:
    if not chains:
        return None

    first_chain = chains[0]
    problem = first_chain.steps[0].title if first_chain.steps else "Problem"
    syntheses = [chain.steps[-1].title for chain in chains if chain.steps]
    synthesis_summary = "; ".join(syntheses[:3])
    return f"{problem}: {synthesis_summary}" if synthesis_summary else problem
