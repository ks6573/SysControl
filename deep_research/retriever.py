"""Retrieval layer — wraps search and fetch functions to build Source objects."""

from __future__ import annotations

import collections.abc
import uuid

from deep_research.config import MAX_PAGE_CHARS, MAX_SEARCH_RESULTS, log
from deep_research.evidence_store import EvidenceStore
from deep_research.schemas import PlanStep, ResearchPlan, Source


def retrieve(
    plan: ResearchPlan,
    search_fn: collections.abc.Callable[[str, int], dict],
    fetch_fn: collections.abc.Callable[[str, int], dict],
    store: EvidenceStore,
    budget: int,
) -> list[Source]:
    """Execute the plan's search steps and fetch new pages.

    Args:
        plan: The current research plan with pending steps.
        search_fn: ``web_search(query, num_results)`` function.
        fetch_fn: ``web_fetch(url, max_chars)`` function.
        store: Evidence store (used to skip already-fetched URLs).
        budget: Maximum number of new sources to fetch this round.

    Returns:
        Newly fetched ``Source`` objects (claims not yet extracted).
    """
    if budget <= 0:
        return []

    # Collect URLs from search results, respecting priority order.
    pending_steps = sorted(
        [s for s in plan.steps if s.status == "pending"],
        key=lambda s: s.priority,
    )

    urls_to_fetch: list[tuple[str, str, str]] = []  # (url, title, step_id)

    for step in pending_steps:
        if len(urls_to_fetch) >= budget:
            break
        _run_search_step(step, search_fn, store, urls_to_fetch, budget)

    # Fetch each URL and build Source objects.
    new_sources: list[Source] = []
    for url, title, _step_id in urls_to_fetch[:budget]:
        source = _fetch_source(url, title, fetch_fn)
        if source is not None:
            new_sources.append(source)

    return new_sources


def _run_search_step(
    step: PlanStep,
    search_fn: collections.abc.Callable[[str, int], dict],
    store: EvidenceStore,
    urls_to_fetch: list[tuple[str, str, str]],
    budget: int,
) -> None:
    """Run a single search step, collecting unseen URLs into *urls_to_fetch*."""
    if step.tool != "web_search" or not step.query:
        step.status = "failed"
        return

    try:
        result = search_fn(step.query, MAX_SEARCH_RESULTS)
    except Exception as exc:
        log.warning("Search failed for '%s': %s", step.query, exc)
        step.status = "failed"
        return

    if "error" in result:
        log.warning("Search error for '%s': %s", step.query, result["error"])
        step.status = "failed"
        return

    step.status = "done"
    seen_in_batch = {u for u, _, _ in urls_to_fetch}

    for hit in result.get("results", []):
        if len(urls_to_fetch) >= budget:
            break
        url = hit.get("url", "")
        if not url or store.has_url(url) or url in seen_in_batch:
            continue
        title = hit.get("title", "")
        urls_to_fetch.append((url, title, step.id))
        seen_in_batch.add(url)


def _fetch_source(
    url: str,
    title: str,
    fetch_fn: collections.abc.Callable[[str, int], dict],
) -> Source | None:
    """Fetch a single URL and wrap it as a Source. Returns None on failure."""
    try:
        result = fetch_fn(url, MAX_PAGE_CHARS)
    except Exception as exc:
        log.warning("Fetch failed for %s: %s", url, exc)
        return None

    if "error" in result:
        log.warning("Fetch error for %s: %s", url, result.get("error"))
        return None

    text = result.get("text", "")
    if not text or len(text) < 50:
        return None  # too short to be useful

    return Source(
        source_id=f"src_{uuid.uuid4().hex[:8]}",
        url=url,
        title=title or result.get("title", ""),
        raw_text=text,
    )
