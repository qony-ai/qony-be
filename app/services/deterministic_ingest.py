from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from uuid import UUID, uuid4

from app.domain.enums import NodeRank, NodeSource
from app.schemas.workspace import GraphNode, GraphValidationSummary, Position, WorkspaceGraph

RANK_X_OFFSETS: dict[NodeRank, float] = {
    NodeRank.PROBLEM_STATEMENT: 0.0,
    NodeRank.SUB_PROBLEM: 340.0,
    NodeRank.HYPOTHESIS: 680.0,
    NodeRank.FRAMEWORK_ANALYSIS: 1020.0,
    NodeRank.SUPPORTING_DATA: 1360.0,
    NodeRank.SYNTHESIS: 1700.0,
}
BRANCH_VERTICAL_GAP = 240.0

SECTION_RE = re.compile(r"^(?P<prefix>\d+(?:\.\d+)*[\.\)])\s*(?P<title>.+)$")
PAGE_MARKER_RE = re.compile(r"^(dokumen .* halaman \d+|halaman \d+|page \d+)$", re.IGNORECASE)
BULLET_RE = re.compile(r"^[\-\*\u2022\u25cf\u25aa]\s*(.+)$")

GENERIC_TITLES = {
    "business case",
    "dokumen internal",
    "executive summary",
    "ringkasan eksekutif",
}
METADATA_PREFIXES = (
    "sponsor",
    "pemilik inisiatif",
    "target",
    "nilai investasi",
    "owner",
    "budget",
    "timeline",
    "go-live",
)
PROBLEM_SECTION_KEYWORDS = (
    "masalah",
    "problem",
    "tantangan",
    "challenge",
    "latar belakang",
    "pain point",
)
ISSUE_KEYWORDS = (
    "stockout",
    "lost sales",
    "manual",
    "reaktif",
    "lambat",
    "rendah",
    "tinggi",
    "delay",
    "bottleneck",
    "silo",
    "kurang",
    "inefficient",
    "tidak",
    "gagal",
    "approval",
    "pembelian",
    "inventory",
    "stok",
    "procurement",
)
EVIDENCE_KEYWORDS = (
    "payback",
    "roi",
    "rp",
    "usd",
    "%",
    "bulan",
    "month",
    "quarter",
    "q1",
    "q2",
    "q3",
    "q4",
    "go-live",
    "investasi",
    "budget",
    "benefit",
    "impact",
)
SYNTHESIS_KEYWORDS = (
    "rekomendasi",
    "recommend",
    "kesimpulan",
    "lanjutkan",
    "implementasi",
    "phased",
    "bertahap",
    "go-live",
)
INDONESIAN_MARKERS = (
    " dan ",
    " yang ",
    " untuk ",
    " dengan ",
    " saat ini ",
    " rekomendasi",
    " pembelian",
    " stok",
)
INVENTORY_KEYWORDS = ("stock", "stok", "inventory", "reorder", "service level", "fast-moving")
PROCUREMENT_KEYWORDS = ("approval", "procurement", "pembelian", "purchase", "vendor", "supplier")
PROCESS_KEYWORDS = ("manual", "spreadsheet", "follow-up", "rekonsiliasi", "komunikasi")


@dataclass(frozen=True, slots=True)
class Section:
    heading: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BranchSeed:
    title: str
    detail: str
    evidence: tuple[str, ...]
    section_hint: str | None = None


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
    language = _detect_language(lines)

    title = _pick_document_title(lines, sections)
    recommendation = _pick_recommendation(lines, sections)
    summary = _build_problem_summary(lines, sections, recommendation)
    evidence_pool = _extract_evidence_pool(lines, sections, recommendation)
    branch_seeds = _build_branch_seeds(
        lines=lines,
        sections=sections,
        evidence_pool=evidence_pool,
        summary=summary,
    )

    if not branch_seeds:
        fallback_title = _localized_label(language, "Core problem", "Masalah inti")
        branch_seeds = [
            BranchSeed(
                title=fallback_title,
                detail=summary or _clip_content(raw_text, 900),
                evidence=tuple(evidence_pool[:2]),
            )
        ]

    root_id = uuid4()
    root_y = ((len(branch_seeds) - 1) * BRANCH_VERTICAL_GAP) / 2 if len(branch_seeds) > 1 else 0.0
    nodes: list[GraphNode] = [
        GraphNode(
            id=root_id,
            rank=NodeRank.PROBLEM_STATEMENT,
            title=_clip_title(title, 255),
            content=_clip_content(summary or raw_text, 1600),
            source=NodeSource.INGEST,
            position=Position(x=RANK_X_OFFSETS[NodeRank.PROBLEM_STATEMENT], y=root_y),
            metadata={"ingest_mode": ingest_mode},
            created_at=created_at,
            updated_at=created_at,
        )
    ]
    edges: list[dict[str, object]] = []

    for branch_index, branch in enumerate(branch_seeds):
        y = branch_index * BRANCH_VERTICAL_GAP

        sub_problem = _make_node(
            rank=NodeRank.SUB_PROBLEM,
            title=_clip_title(branch.title, 255),
            content=_clip_content(branch.detail, 1200),
            created_at=created_at,
            y=y,
            branch_index=branch_index,
            section_hint=branch.section_hint,
        )
        hypothesis = _make_node(
            rank=NodeRank.HYPOTHESIS,
            title=_localized_label(language, "Cause hypothesis", "Hipotesis penyebab"),
            content=_build_hypothesis_content(branch.title, branch.detail, language),
            created_at=created_at,
            y=y,
            branch_index=branch_index,
            section_hint=branch.section_hint,
        )
        analysis = _make_node(
            rank=NodeRank.FRAMEWORK_ANALYSIS,
            title=_localized_label(language, "Analysis lens", "Kerangka analisis"),
            content=_build_framework_content(branch.detail, language),
            created_at=created_at,
            y=y,
            branch_index=branch_index,
            section_hint=branch.section_hint,
        )
        evidence = _make_node(
            rank=NodeRank.SUPPORTING_DATA,
            title=_localized_label(language, "Supporting evidence", "Bukti pendukung"),
            content=_build_evidence_content(branch.evidence, recommendation, language),
            created_at=created_at,
            y=y,
            branch_index=branch_index,
            section_hint=branch.section_hint,
        )
        synthesis = _make_node(
            rank=NodeRank.SYNTHESIS,
            title=_localized_label(language, "Recommended direction", "Arah rekomendasi"),
            content=_build_synthesis_content(branch.title, recommendation, language),
            created_at=created_at,
            y=y,
            branch_index=branch_index,
            section_hint=branch.section_hint,
        )

        nodes.extend([sub_problem, hypothesis, analysis, evidence, synthesis])
        for source_id, target_id in (
            (root_id, sub_problem.id),
            (sub_problem.id, hypothesis.id),
            (hypothesis.id, analysis.id),
            (analysis.id, evidence.id),
            (evidence.id, synthesis.id),
        ):
            edges.append(_make_edge(source_id=source_id, target_id=target_id, created_at=created_at))

    attributes: dict[str, object] = {"ingest_mode": ingest_mode}
    if provider_attempted:
        attributes["provider_attempted"] = provider_attempted

    validation = GraphValidationSummary(
        is_valid=True,
        reachable_node_count=len(nodes),
        complete_branch_count=len(branch_seeds),
    )
    return WorkspaceGraph.model_validate(
        {
            "nodes": [node.model_dump(mode="json") for node in nodes],
            "edges": edges,
            "metadata": {
                "project_id": str(project_id),
                "workspace_id": str(workspace_id),
                "version": workspace_version,
                "updated_at": created_at.isoformat(),
                "validation": validation.model_dump(mode="json"),
                "attributes": attributes,
            },
        }
    )


def _make_node(
    *,
    rank: NodeRank,
    title: str,
    content: str,
    created_at: datetime,
    y: float,
    branch_index: int,
    section_hint: str | None,
) -> GraphNode:
    metadata: dict[str, object] = {"branch_index": branch_index}
    if section_hint:
        metadata["section_hint"] = section_hint
    return GraphNode(
        id=uuid4(),
        rank=rank,
        title=title,
        content=content,
        source=NodeSource.INGEST,
        position=Position(x=RANK_X_OFFSETS[rank], y=y),
        metadata=metadata,
        created_at=created_at,
        updated_at=created_at,
    )


def _make_edge(*, source_id, target_id, created_at: datetime) -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "source": str(source_id),
        "target": str(target_id),
        "label": None,
        "metadata": {},
        "created_at": created_at.isoformat(),
        "updated_at": created_at.isoformat(),
    }


def _clean_lines(raw_text: str) -> list[str]:
    normalized = (
        raw_text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\xa0", " ")
        .replace("\u2022", "•")
        .replace("\u25cf", "•")
        .replace("\u25aa", "•")
    )
    lines: list[str] = []
    for raw_line in normalized.split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if PAGE_MARKER_RE.match(line):
            continue
        lines.append(line)
    return _dedupe_nearby(lines)


def _extract_sections(lines: list[str]) -> list[Section]:
    if not lines:
        return []

    sections: list[Section] = []
    current_heading = "Overview"
    current_lines: list[str] = []

    for line in lines:
        heading = _detect_section_heading(line)
        if heading:
            if current_lines:
                sections.append(Section(heading=current_heading, lines=tuple(current_lines)))
            current_heading = heading
            current_lines = []
            continue
        current_lines.append(line)

    if current_lines:
        sections.append(Section(heading=current_heading, lines=tuple(current_lines)))
    return sections


def _detect_section_heading(line: str) -> str | None:
    if _is_metadata_line(line):
        return None
    match = SECTION_RE.match(line)
    if match:
        title = match.group("title").strip(" .:-")
        if len(title.split()) <= 12:
            return title
    if line.endswith(":") and len(line.split()) <= 8:
        return line[:-1].strip()
    if line.isupper() and 2 <= len(line.split()) <= 8 and line.casefold() not in GENERIC_TITLES:
        return line.title()
    return None


def _pick_document_title(lines: list[str], sections: list[Section]) -> str:
    title_lines: list[str] = []
    for line in lines[:10]:
        lower = line.casefold()
        if lower in GENERIC_TITLES or _is_metadata_line(line):
            continue
        if BULLET_RE.match(line) or SECTION_RE.match(line):
            continue
        if ":" in line or line.endswith((".", "!", "?")):
            continue
        if any(keyword in lower for keyword in SYNTHESIS_KEYWORDS):
            continue
        if len(line) > 120:
            continue
        title_lines.append(line)
        if len(title_lines) == 2:
            break

    if len(title_lines) >= 2 and len(title_lines[0]) < 80 and len(title_lines[1]) < 60:
        return _clip_title(f"{title_lines[0]} {title_lines[1]}", 255)
    if title_lines:
        return _clip_title(title_lines[0], 255)

    for section in sections:
        if section.heading != "Overview":
            return _clip_title(section.heading, 255)

    return "Untitled problem"


def _build_problem_summary(lines: list[str], sections: list[Section], recommendation: str | None) -> str:
    parts: list[str] = []
    if recommendation:
        parts.append(recommendation)

    problem_section = _find_section(sections, PROBLEM_SECTION_KEYWORDS)
    if problem_section is not None:
        narrative = [line for line in problem_section.lines if not _is_bullet_line(line)]
        if narrative:
            parts.append(_collapse_lines(narrative[:3]))
        bullets = [_clean_bullet(line) for line in problem_section.lines if _is_bullet_line(line)]
        if bullets:
            parts.append("Key issues:\n- " + "\n- ".join(bullets[:3]))

    if not parts:
        narrative_lines = [line for line in lines if not _is_metadata_line(line) and not _is_bullet_line(line)]
        parts.append(_collapse_lines(narrative_lines[:5]))

    return _clip_content("\n\n".join(part for part in parts if part).strip(), 1600)


def _build_branch_seeds(
    *,
    lines: list[str],
    sections: list[Section],
    evidence_pool: list[str],
    summary: str,
) -> list[BranchSeed]:
    candidates: list[tuple[str, str | None]] = []
    problem_section = _find_section(sections, PROBLEM_SECTION_KEYWORDS)

    if problem_section is not None:
        bullet_candidates = [_clean_bullet(line) for line in problem_section.lines if _is_bullet_line(line)]
        if bullet_candidates:
            candidates.extend((item, problem_section.heading) for item in bullet_candidates)
        else:
            candidates.extend((line, problem_section.heading) for line in problem_section.lines if _looks_like_issue_line(line))

    if not candidates:
        candidates.extend((line, None) for line in lines if _is_bullet_line(line) and _looks_like_issue_line(line))
    if not candidates:
        candidates.extend((line, None) for line in lines if _looks_like_issue_line(line))
    if not candidates and summary:
        candidates.append((summary.split("\n", 1)[0], None))

    seeds: list[BranchSeed] = []
    seen: set[str] = set()
    for detail, heading in candidates:
        normalized = _normalize_key(detail)
        if normalized in seen:
            continue
        seen.add(normalized)
        evidence = _select_supporting_evidence(detail=detail, evidence_pool=evidence_pool)
        seeds.append(
            BranchSeed(
                title=_compact_title(detail),
                detail=_clip_content(detail, 1200),
                evidence=evidence,
                section_hint=heading,
            )
        )
        if len(seeds) == 3:
            break
    return seeds


def _extract_evidence_pool(lines: list[str], sections: list[Section], recommendation: str | None) -> list[str]:
    candidates: list[str] = []

    for line in lines:
        lower = line.casefold()
        if _is_metadata_line(line) or any(keyword in lower for keyword in EVIDENCE_KEYWORDS) or _contains_metric(line):
            candidates.append(line)

    benefit_section = _find_section(sections, ("benefit", "impact", "manfaat", "financial", "roi", "investasi"))
    if benefit_section is not None:
        candidates.extend(benefit_section.lines)

    if recommendation:
        candidates.insert(0, recommendation)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_key(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(candidate)
    return unique[:8]


def _pick_recommendation(lines: list[str], sections: list[Section]) -> str | None:
    for line in lines:
        lower = line.casefold()
        if any(keyword in lower for keyword in SYNTHESIS_KEYWORDS):
            return _clip_content(line, 500)

    recommendation_section = _find_section(sections, ("rekomendasi", "recommend", "kesimpulan"))
    if recommendation_section is not None and recommendation_section.lines:
        return _clip_content(_collapse_lines(recommendation_section.lines[:3]), 500)
    return None


def _select_supporting_evidence(*, detail: str, evidence_pool: list[str]) -> tuple[str, ...]:
    if not evidence_pool:
        return ()
    scored = sorted(
        (
            (_evidence_score(detail, line), index, line)
            for index, line in enumerate(evidence_pool)
        ),
        key=lambda item: (-item[0], item[1]),
    )
    selected = [line for score, _, line in scored if score > 0][:2]
    if not selected:
        selected = evidence_pool[:2]
    return tuple(selected)


def _build_hypothesis_content(title: str, detail: str, language: str) -> str:
    lower = detail.casefold()
    if any(keyword in lower for keyword in INVENTORY_KEYWORDS):
        return _localized_label(
            language,
            "Inventory visibility and reorder logic are likely too weak to support timely action on this issue.",
            "Visibilitas inventory dan logika reorder kemungkinan belum cukup kuat untuk menangani isu ini secara tepat waktu.",
        )
    if any(keyword in lower for keyword in PROCUREMENT_KEYWORDS):
        return _localized_label(
            language,
            "Approval flow, vendor coordination, or purchasing controls are likely creating the delay behind this issue.",
            "Alur approval, koordinasi vendor, atau kontrol pembelian kemungkinan menjadi penyebab utama keterlambatan pada isu ini.",
        )
    if any(keyword in lower for keyword in PROCESS_KEYWORDS):
        return _localized_label(
            language,
            "Fragmented manual workflows are likely causing low visibility and slow response around this issue.",
            "Workflow manual yang terfragmentasi kemungkinan menyebabkan visibilitas rendah dan respons lambat pada isu ini.",
        )
    return _localized_label(
        language,
        f"The issue around {title.lower()} likely stems from fragmented processes, weak visibility, or unclear decision ownership.",
        f"Isu pada {title.lower()} kemungkinan berasal dari proses yang terfragmentasi, visibilitas yang lemah, atau kepemilikan keputusan yang tidak jelas.",
    )


def _build_framework_content(detail: str, language: str) -> str:
    lower = detail.casefold()
    if any(keyword in lower for keyword in INVENTORY_KEYWORDS):
        return _localized_label(
            language,
            "Review demand signals, reorder thresholds, inventory visibility, and escalation triggers.",
            "Telaah demand signal, ambang reorder, visibilitas inventory, dan trigger eskalasi.",
        )
    if any(keyword in lower for keyword in PROCUREMENT_KEYWORDS):
        return _localized_label(
            language,
            "Review request intake, approval latency, supplier lead times, and purchasing governance.",
            "Telaah intake permintaan, latency approval, lead time supplier, dan tata kelola pembelian.",
        )
    return _localized_label(
        language,
        "Review process handoffs, control points, ownership, and the quality of supporting operational data.",
        "Telaah handoff proses, titik kontrol, ownership, dan kualitas data operasional pendukung.",
    )


def _build_evidence_content(evidence: tuple[str, ...], recommendation: str | None, language: str) -> str:
    evidence_lines = list(evidence)
    if recommendation and recommendation not in evidence_lines:
        evidence_lines.append(recommendation)
    if not evidence_lines:
        return _localized_label(
            language,
            "No structured evidence was extracted, so this branch should be validated with operating data and stakeholder interviews.",
            "Belum ada bukti terstruktur yang terekstrak, sehingga cabang ini perlu divalidasi dengan data operasional dan wawancara stakeholder.",
        )
    prefix = _localized_label(language, "Evidence:", "Bukti:")
    return _clip_content(f"{prefix}\n- " + "\n- ".join(evidence_lines[:3]), 1200)


def _build_synthesis_content(title: str, recommendation: str | None, language: str) -> str:
    if recommendation:
        return _clip_content(
            _localized_label(
                language,
                f"{recommendation} Apply the rollout first to reduce risk around {title.lower()}.",
                f"{recommendation} Prioritaskan rollout awal untuk mengurangi risiko pada {title.lower()}.",
            ),
            1200,
        )
    return _localized_label(
        language,
        f"Use this branch to define the first operational intervention around {title.lower()} and validate impact before scaling.",
        f"Gunakan cabang ini untuk menentukan intervensi operasional awal pada {title.lower()} dan validasi dampaknya sebelum diskalakan.",
    )


def _compact_title(text: str) -> str:
    cleaned = _clean_bullet(text).strip(" .:-")
    lowered = cleaned.casefold()
    for prefix in ("saat ini ", "tim ", "proses ", "the ", "current "):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            lowered = cleaned.casefold()
            break

    for separator in (" karena ", " sehingga ", ",", ";", ":"):
        index = lowered.find(separator)
        if index > 24:
            cleaned = cleaned[:index].strip()
            break

    words = cleaned.split()
    if len(words) > 10:
        cleaned = " ".join(words[:10])
    return _clip_title(cleaned or "Untitled branch", 255)


def _find_section(sections: list[Section], keywords: Iterable[str]) -> Section | None:
    for section in sections:
        heading = section.heading.casefold()
        if any(keyword in heading for keyword in keywords):
            return section
    return None


def _collapse_lines(lines: Iterable[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(line.strip() for line in lines if line.strip())).strip()


def _is_metadata_line(line: str) -> bool:
    lowered = line.casefold()
    return any(lowered.startswith(prefix) for prefix in METADATA_PREFIXES)


def _is_bullet_line(line: str) -> bool:
    return BULLET_RE.match(line) is not None


def _clean_bullet(line: str) -> str:
    match = BULLET_RE.match(line)
    return (match.group(1) if match else line).strip()


def _looks_like_issue_line(line: str) -> bool:
    lowered = _clean_bullet(line).casefold()
    if len(lowered) < 24:
        return False
    return any(keyword in lowered for keyword in ISSUE_KEYWORDS) or _contains_metric(line)


def _contains_metric(line: str) -> bool:
    lowered = line.casefold()
    return bool(re.search(r"\b\d+\b", line)) or any(keyword in lowered for keyword in EVIDENCE_KEYWORDS)


def _evidence_score(detail: str, evidence: str) -> int:
    score = 0
    detail_tokens = set(_tokenize(detail))
    evidence_tokens = set(_tokenize(evidence))
    score += len(detail_tokens & evidence_tokens) * 3
    if _contains_metric(evidence):
        score += 2
    if any(token in evidence.casefold() for token in ("payback", "investasi", "go-live", "approval", "stok", "inventory")):
        score += 1
    return score


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]+", text.casefold()) if len(token) > 2]


def _dedupe_nearby(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    recent: set[str] = set()
    for line in lines:
        normalized = _normalize_key(line)
        if normalized in recent:
            continue
        cleaned.append(line)
        recent = {normalized}
    return cleaned


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _detect_language(lines: list[str]) -> str:
    text = f" {' '.join(lines).casefold()} "
    score = sum(marker in text for marker in INDONESIAN_MARKERS)
    return "id" if score >= 2 else "en"


def _localized_label(language: str, english: str, indonesian: str) -> str:
    return indonesian if language == "id" else english


def _clip_title(value: str, limit: int) -> str:
    stripped = re.sub(r"\s+", " ", value).strip()
    return stripped if len(stripped) <= limit else stripped[: limit - 1].rstrip() + "…"


def _clip_content(value: str, limit: int) -> str:
    stripped = value.strip()
    return stripped if len(stripped) <= limit else stripped[: limit - 1].rstrip() + "…"
