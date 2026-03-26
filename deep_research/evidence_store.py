"""In-memory evidence store for collected sources and claims."""

from __future__ import annotations

from deep_research.config import SOURCE_TYPE_SCORES
from deep_research.schemas import Claim, Source


class EvidenceStore:
    """Manages gathered sources, deduplicates by URL, and provides summaries."""

    def __init__(self) -> None:
        self._sources: list[Source] = []
        self._seen_urls: set[str] = set()

    # ── Mutation ──────────────────────────────────────────────────────────────

    def add_source(self, source: Source) -> bool:
        """Add a source if its URL hasn't been seen before. Returns True if added."""
        if not source.url:
            # No URL — cannot deduplicate, always accept.
            self._sources.append(source)
            return True
        key = source.url.rstrip("/").lower()
        if key in self._seen_urls:
            return False
        self._seen_urls.add(key)
        source.reliability_score = SOURCE_TYPE_SCORES.get(
            source.source_type, SOURCE_TYPE_SCORES["unknown"]
        )
        self._sources.append(source)
        return True

    def has_url(self, url: str) -> bool:
        """Check whether a URL (normalised) has already been fetched."""
        return url.rstrip("/").lower() in self._seen_urls

    # ── Queries ───────────────────────────────────────────────────────────────

    def source_count(self) -> int:
        """Number of unique sources stored."""
        return len(self._sources)

    def all_sources(self) -> list[Source]:
        """Return all sources in insertion order."""
        return list(self._sources)

    def has_claims(self) -> bool:
        """Return True if any source has at least one claim."""
        return any(src.claims for src in self._sources)

    def all_claims(self) -> list[tuple[Claim, Source]]:
        """Flat list of (claim, parent_source) pairs across all sources."""
        pairs: list[tuple[Claim, Source]] = []
        for src in self._sources:
            for claim in src.claims:
                pairs.append((claim, src))
        return pairs

    # ── Summaries for LLM prompts ─────────────────────────────────────────────

    def claims_summary(self) -> str:
        """Format all claims as a numbered text block for LLM prompts."""
        lines: list[str] = []
        for i, (claim, src) in enumerate(self.all_claims(), 1):
            lines.append(
                f"{i}. [{src.source_id}] ({src.source_type}, "
                f"score={src.reliability_score:.2f}): {claim.text}"
            )
            if claim.quote:
                lines.append(f'   Quote: "{claim.quote}"')
        return "\n".join(lines) if lines else "(no claims collected yet)"

    def to_citation_list(self) -> list[dict]:
        """Build a citation list for the final report."""
        return [
            {
                "id": src.source_id,
                "title": src.title or "(untitled)",
                "url": src.url,
                "type": src.source_type,
            }
            for src in self._sources
            if src.claims  # only cite sources that contributed claims
        ]
