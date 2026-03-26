"""Verification engine — cross-checks claims across sources."""

from __future__ import annotations

from openai import OpenAI

from deep_research.config import llm_json
from deep_research.evidence_store import EvidenceStore
from deep_research.schemas import VerificationResult

_SYSTEM = """\
You are a verification analyst. Given a set of claims from multiple sources, \
determine which claims are well-supported, disputed, or insufficiently evidenced.

Return ONLY valid JSON:
{
  "verifications": [
    {
      "claim_text": "the claim being checked",
      "status": "verified" | "disputed" | "insufficient",
      "supporting_source_ids": ["src_abc", "src_def"],
      "contradicting_source_ids": [],
      "notes": "brief explanation of the verdict"
    }
  ]
}

Rules:
- "verified": supported by 2+ independent sources with direct evidence.
- "disputed": contradicted by at least one source — note the disagreement.
- "insufficient": only one source, or sources are weak/indirect.
- Group near-identical claims and verify them together.
- Flag stale or outdated information (e.g. claims with old dates on a \
time-sensitive topic).
- Do NOT mark a claim as verified just because multiple sources copy \
the same original report — look for truly independent evidence.\
"""


def verify_claims(
    client: OpenAI,
    model: str,
    store: EvidenceStore,
) -> list[VerificationResult]:
    """Cross-check all collected claims and return verification results."""
    if not store.has_claims():
        return []
    summary = store.claims_summary()

    user_prompt = (
        "Below are all claims collected so far, tagged with their source IDs "
        "and reliability scores. Verify each important claim.\n\n"
        f"{summary}"
    )

    data = llm_json(client, model, _SYSTEM, user_prompt)

    results: list[VerificationResult] = []
    for item in data.get("verifications", []):
        claim_text = item.get("claim_text", "").strip()
        if not claim_text:
            continue
        results.append(
            VerificationResult(
                claim_text=claim_text,
                status=item.get("status", "insufficient"),
                supporting_source_ids=item.get("supporting_source_ids", []),
                contradicting_source_ids=item.get("contradicting_source_ids", []),
                notes=item.get("notes", ""),
            )
        )

    return results
