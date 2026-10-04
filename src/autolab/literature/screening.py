"""Deterministic bounds and diversity applied to structured relevance scores."""
import json
from .models import EvidenceRole, LiteratureLimits, ScreeningResult


class EvidenceOutputError(ValueError):
    pass


def screening_candidates(results, limits: LiteratureLimits):
    candidates = {}
    size = 0
    for n, paper in enumerate(results):
        if not paper.title.strip() or not (paper.abstract or "").strip():
            continue
        identifier = f"PAPER_{n+1:04d}"
        row = {"candidate_id": identifier, "title": paper.title, "abstract": paper.abstract[:limits.abstract_chars],
               "year": paper.year, "categories": paper.categories[:5]}
        size += len(json.dumps(row))
        if size > limits.max_screen_chars:
            break
        candidates[identifier] = (paper, row)
    return candidates


def validate_screening(screening: ScreeningResult, candidates) -> None:
    identifiers = [p.candidate_id for p in screening.papers]
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != set(candidates):
        raise EvidenceOutputError("Screening must cover each supplied candidate exactly once")


def select_top_k(screening: ScreeningResult, candidates, limits: LiteratureLimits):
    validate_screening(screening, candidates)
    ranked = sorted((p for p in screening.papers if p.relevance_score >= limits.min_relevance),
                    key=lambda p: (-p.relevance_score, p.candidate_id))
    selected = []
    # Reserve a place for relevant contradictory work and methodological work;
    # these labels express relevance to the question, not scientific truth.
    for role in (EvidenceRole.CONTRADICTING, EvidenceRole.METHOD):
        paper = next((p for p in ranked if p.evidence_role == role), None)
        if paper and len(selected) < limits.top_k:
            selected.append(paper)
    for paper in ranked:
        if paper not in selected and len(selected) < limits.top_k:
            selected.append(paper)
    return selected
