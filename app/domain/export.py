from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from app.core.exceptions import DomainValidationError
from app.domain.enums import NodeRank
from app.domain.graph import ensure_valid_graph
from app.schemas.export import (
    ExportChain,
    ExportReport,
    ExportReportBranch,
    ExportReportSection,
    ExportStep,
)
from app.schemas.workspace import GraphNode, WorkspaceGraph


def build_export_preview(
    graph: WorkspaceGraph,
    *,
    path_limit: int = 250,
) -> tuple[list[ExportChain], ExportReport | None, list[str]]:
    ensure_valid_graph(graph)
    warnings: list[str] = []

    if not graph.nodes:
        warnings.append("The workspace is empty, so there is no exportable report content yet.")
        return [], None, warnings

    nodes_by_id: dict[UUID, GraphNode] = {node.id: node for node in graph.nodes}
    node_order: dict[UUID, int] = {node.id: index for index, node in enumerate(graph.nodes)}
    children_by_id: dict[UUID, list[UUID]] = defaultdict(list)
    for edge in graph.edges:
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
                node_order.get(child_id, 0),
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
    if not chains:
        warnings.append(
            "No complete Rank 1 through Rank 6 branches are available yet. Finish a full branch to generate a premium export."
        )

    return chains, build_structured_report(graph, chains), warnings


def build_fallback_narrative(chains: list[ExportChain]) -> str | None:
    if not chains:
        return None

    first_chain = chains[0]
    problem = first_chain.steps[0].title if first_chain.steps else "Problem"
    syntheses = [chain.steps[-1].title for chain in chains if chain.steps]
    synthesis_summary = "; ".join(syntheses[:3])
    return f"{problem}: {synthesis_summary}" if synthesis_summary else problem


def build_structured_report(
    graph: WorkspaceGraph,
    chains: list[ExportChain],
) -> ExportReport | None:
    if not chains:
        return None

    root = next(
        (node for node in graph.nodes if node.rank == NodeRank.PROBLEM_STATEMENT),
        None,
    )
    if root is None:
        return None

    sections_by_id: dict[str, ExportReportSection] = {}
    section_order: list[str] = []
    takeaways: list[str] = []

    for chain in chains:
        steps_by_rank: dict[int, list[ExportStep]] = defaultdict(list)
        for step in chain.steps:
            steps_by_rank[int(step.rank)].append(step)

        section_step = steps_by_rank.get(int(NodeRank.SUB_PROBLEM), [None])[0]
        section_id = str(section_step.node_id) if section_step is not None else "ungrouped"
        if section_id not in sections_by_id:
            section_order.append(section_id)
            sections_by_id[section_id] = ExportReportSection(
                section_id=section_id,
                title=section_step.title if section_step is not None else "Unscoped branch",
                overview=section_step.content if section_step is not None else None,
            )

        branch = ExportReportBranch(
            branch_id=chain.chain_id,
            headline=_resolve_branch_headline(chain),
            summary=_build_branch_summary(chain),
            hypothesis=steps_by_rank.get(int(NodeRank.HYPOTHESIS), [None])[0],
            analysis=steps_by_rank.get(int(NodeRank.FRAMEWORK_ANALYSIS), [None])[0],
            evidence=steps_by_rank.get(int(NodeRank.SUPPORTING_DATA), []),
            synthesis=steps_by_rank.get(int(NodeRank.SYNTHESIS), [None])[0],
        )
        section = sections_by_id[section_id]
        section.branches.append(branch)
        section.branch_count = len(section.branches)
        if branch.synthesis is not None:
            takeaways.append(branch.synthesis.title)
            if branch.synthesis.title not in section.synthesis_highlights:
                section.synthesis_highlights.append(branch.synthesis.title)
        for evidence in branch.evidence:
            if evidence.title not in section.evidence_highlights:
                section.evidence_highlights.append(evidence.title)

    sections = [sections_by_id[section_id] for section_id in section_order]
    for section in sections:
        section.summary = _build_section_summary(section)
        section.evidence_highlights = section.evidence_highlights[:4]
        section.synthesis_highlights = section.synthesis_highlights[:4]

    return ExportReport(
        title=root.title,
        subtitle=root.content,
        summary=_build_report_summary(root.title, sections),
        key_takeaways=list(dict.fromkeys(takeaways))[:5],
        sections=sections,
    )


def _resolve_branch_headline(chain: ExportChain) -> str:
    for preferred_rank in (
        NodeRank.SYNTHESIS,
        NodeRank.HYPOTHESIS,
        NodeRank.FRAMEWORK_ANALYSIS,
    ):
        step = next((item for item in chain.steps if item.rank == preferred_rank), None)
        if step is not None:
            return step.title

    return chain.steps[-1].title if chain.steps else "Untitled branch"


def _build_branch_summary(chain: ExportChain) -> str | None:
    ranked_steps = {int(step.rank): step for step in chain.steps}
    synthesis = ranked_steps.get(int(NodeRank.SYNTHESIS))
    analysis = ranked_steps.get(int(NodeRank.FRAMEWORK_ANALYSIS))
    evidence = ranked_steps.get(int(NodeRank.SUPPORTING_DATA))

    segments = [
        synthesis.title if synthesis is not None else None,
        synthesis.content if synthesis is not None else None,
        analysis.content if analysis is not None else None,
        evidence.content if evidence is not None else None,
    ]
    cleaned = [segment.strip() for segment in segments if isinstance(segment, str) and segment.strip()]
    if not cleaned:
        return None
    return " ".join(cleaned[:3])


def _build_section_summary(section: ExportReportSection) -> str | None:
    synthesis_titles = [
        branch.synthesis.title
        for branch in section.branches
        if branch.synthesis is not None
    ]
    if synthesis_titles:
        return f"{section.title} resolves into {', '.join(synthesis_titles[:3])}."

    branch_summaries = [branch.summary for branch in section.branches if branch.summary]
    if branch_summaries:
        return branch_summaries[0]

    return section.overview


def _build_report_summary(title: str, sections: list[ExportReportSection]) -> str:
    if not sections:
        return title

    section_titles = ", ".join(section.title for section in sections[:3])
    return (
        f"{title} is organized into {len(sections)} core sections. "
        f"Primary sub-problems covered: {section_titles}."
    )
