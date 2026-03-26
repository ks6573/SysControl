"""Orchestrator — runs the iterative deep-research agent loop."""

from __future__ import annotations

import collections.abc
import time

from openai import OpenAI

from deep_research.config import MAX_RESEARCH_LOOPS, MAX_SOURCES, log
from deep_research.critic import critique
from deep_research.evidence_store import EvidenceStore
from deep_research.extractor import extract_claims
from deep_research.planner import make_plan
from deep_research.query_analyzer import analyze_query
from deep_research.retriever import retrieve
from deep_research.schemas import ResearchTask, VerificationResult
from deep_research.synthesizer import synthesize
from deep_research.verifier import verify_claims


def orchestrate(
    question: str,
    search_fn: collections.abc.Callable[[str, int], dict],
    fetch_fn: collections.abc.Callable[[str, int], dict],
    llm_client: OpenAI,
    model: str,
    max_loops: int = MAX_RESEARCH_LOOPS,
    max_sources: int = MAX_SOURCES,
) -> dict:
    """Run a full deep-research investigation and return a structured report.

    Args:
        question: The user's research question.
        search_fn: ``web_search(query, num_results)`` callable.
        fetch_fn: ``web_fetch(url, max_chars)`` callable.
        llm_client: OpenAI-compatible client for internal reasoning.
        model: Model identifier string.
        max_loops: Maximum research iterations before forcing synthesis.
        max_sources: Maximum total sources to consult.

    Returns:
        A dict with ``answer``, ``summary``, ``key_findings``,
        ``uncertainties``, ``sources``, and ``metadata``.
    """
    start = time.monotonic()

    # Step 1 — Analyze the query.
    task = analyze_query(llm_client, model, question)
    log.info("Research task: %s (%d subquestions)", task.research_objective, len(task.subquestions))

    store = EvidenceStore()
    verifications: list[VerificationResult] = []

    loops_used = 0
    for attempt in range(max_loops):
        loops_used = attempt + 1
        log.info("Research loop %d/%d (sources=%d)", loops_used, max_loops, store.source_count())

        # Step 2 — Plan.
        plan = make_plan(llm_client, model, task, store, verifications)

        # Step 3 — Retrieve.
        budget = max_sources - store.source_count()
        new_sources = retrieve(plan, search_fn, fetch_fn, store, budget)

        # Step 4 — Extract claims from new sources (skip dupes before LLM call).
        for source in new_sources:
            if store.has_url(source.url):
                continue
            result = extract_claims(llm_client, model, task, source)
            source.claims = result.claims
            source.source_type = result.source_type
            source.publisher = result.publisher
            source.published_at = result.published_at
            store.add_source(source)

        # Step 5 — Verify claims across all sources.
        verifications = verify_claims(llm_client, model, store)

        # Step 6 — Check sufficiency.
        if _is_sufficient(task, verifications, store):
            # Step 7 — Synthesize.
            draft = synthesize(llm_client, model, task, store, verifications)

            # Step 8 — Critique.
            review = critique(llm_client, model, task, draft, store, verifications)
            if review.passed:
                return _format_report(
                    draft, store, verifications, loops_used, start,
                )
            log.info("Critic rejected draft: %s", review.issues)

        # Budget exhausted — stop looping.
        if store.source_count() >= max_sources:
            log.info("Source budget exhausted (%d/%d)", store.source_count(), max_sources)
            break

    # Max loops or budget reached — synthesize with explicit uncertainty.
    draft = synthesize(llm_client, model, task, store, verifications)
    return _format_report(
        draft, store, verifications, loops_used, start, exhausted=True,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_sufficient(
    task: ResearchTask,
    verifications: list[VerificationResult],
    store: EvidenceStore,
) -> bool:
    """Heuristic: have we gathered enough verified evidence to answer?"""
    if store.source_count() < 3:
        return False
    if not verifications:
        return False
    verified = sum(1 for v in verifications if v.status == "verified")
    total = len(verifications)
    return (verified / total) >= 0.5 if total > 0 else False


def _format_report(
    draft: str,
    store: EvidenceStore,
    verifications: list[VerificationResult],
    loops_used: int,
    start: float,
    *,
    exhausted: bool = False,
) -> dict:
    """Build the final structured report dict."""
    verified = sum(1 for v in verifications if v.status == "verified")
    disputed = sum(1 for v in verifications if v.status == "disputed")
    insufficient = sum(1 for v in verifications if v.status == "insufficient")

    uncertainties: list[str] = []
    if exhausted:
        uncertainties.append(
            "Research loop limit reached — some claims may not be fully verified."
        )
    for v in verifications:
        if v.status == "disputed":
            uncertainties.append(f"Disputed: {v.claim_text} — {v.notes}")
        elif v.status == "insufficient":
            uncertainties.append(f"Unverified: {v.claim_text}")

    key_findings = [
        {
            "finding": v.claim_text,
            "status": v.status,
            "citations": v.supporting_source_ids,
        }
        for v in verifications
        if v.status == "verified"
    ]

    return {
        "answer": draft,
        "key_findings": key_findings,
        "uncertainties": uncertainties,
        "sources": store.to_citation_list(),
        "metadata": {
            "loops_used": loops_used,
            "sources_consulted": store.source_count(),
            "claims_verified": verified,
            "claims_disputed": disputed,
            "claims_insufficient": insufficient,
            "elapsed_seconds": round(time.monotonic() - start, 1),
        },
    }
