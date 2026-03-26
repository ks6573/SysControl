"""Shared data models for the deep-research pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResearchTask:
    """Structured representation of the user's research question."""

    user_question: str
    research_objective: str = ""
    subquestions: list[str] = field(default_factory=list)
    needs_current_info: bool = True
    required_output_format: str = "detailed"
    constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)


@dataclass
class PlanStep:
    """One step in a research plan."""

    id: str
    goal: str
    tool: str = "web_search"  # "web_search" | "read_page"
    query: str = ""
    priority: int = 1
    status: str = "pending"  # "pending" | "done" | "failed"


@dataclass
class ResearchPlan:
    """A stepwise research plan with open questions and verification targets."""

    steps: list[PlanStep] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    verification_targets: list[str] = field(default_factory=list)


@dataclass
class Claim:
    """A single factual claim extracted from a source."""

    claim_id: str
    text: str
    support_type: str = "uncertain"  # "direct" | "partial" | "uncertain"
    quote: str = ""
    extracted_data: dict = field(default_factory=dict)


@dataclass
class Source:
    """A retrieved source with its extracted claims."""

    source_id: str
    url: str = ""
    title: str = ""
    publisher: str = ""
    published_at: str = ""
    source_type: str = "unknown"  # "official" | "news" | "paper" | "blog" | "forum" | "dataset"
    reliability_score: float = 0.5
    claims: list[Claim] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class VerificationResult:
    """Cross-source verification status for a claim."""

    claim_text: str
    status: str = "insufficient"  # "verified" | "disputed" | "insufficient"
    supporting_source_ids: list[str] = field(default_factory=list)
    contradicting_source_ids: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class CriticReview:
    """Result of the final quality check."""

    passed: bool = False
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
