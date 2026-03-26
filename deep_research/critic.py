"""Critic — final quality and factuality check before returning the answer."""

from __future__ import annotations

from openai import OpenAI

from deep_research.config import llm_json
from deep_research.evidence_store import EvidenceStore
from deep_research.schemas import CriticReview, ResearchTask, VerificationResult

_SYSTEM = """\
You are a research quality critic. Review the draft answer below against the \
evidence and verification results. Check for problems and decide whether the \
answer is ready to return.

Return ONLY valid JSON:
{
  "pass": true or false,
  "issues": ["list of specific problems found"],
  "suggestions": ["actionable improvements if pass=false"]
}

Check for:
1. Completeness — does the answer address the original question and its subquestions?
2. Citation coverage — are major factual claims cited with source IDs?
3. Factual grounding — is anything stated that is NOT in the evidence?
4. Uncertainty handling — are gaps and limitations disclosed?
5. Hallucination — are there any facts that cannot be traced to the evidence?
6. Contradiction handling — are disagreements between sources reported honestly?

Be strict. Only pass answers that meet all six criteria.\
"""


def critique(
    client: OpenAI,
    model: str,
    task: ResearchTask,
    draft: str,
    store: EvidenceStore,
    verifications: list[VerificationResult],
) -> CriticReview:
    """Run a final quality check on the draft answer."""
    parts = [
        f"Original question: {task.user_question}\n",
        f"Subquestions: {task.subquestions}\n",
        "--- DRAFT ANSWER ---\n",
        draft,
        "\n--- EVIDENCE SUMMARY ---\n",
        store.claims_summary(),
    ]

    if verifications:
        parts.append("\n--- VERIFICATION STATUS ---")
        for v in verifications:
            parts.append(f"- [{v.status}] {v.claim_text}")

    data = llm_json(client, model, _SYSTEM, "\n".join(parts))

    return CriticReview(
        passed=bool(data.get("pass", False)),
        issues=data.get("issues", []),
        suggestions=data.get("suggestions", []),
    )
