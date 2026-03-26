"""Synthesis engine — produces a citation-backed answer from verified evidence."""

from __future__ import annotations

from openai import OpenAI

from deep_research.config import llm_call
from deep_research.evidence_store import EvidenceStore
from deep_research.schemas import ResearchTask, VerificationResult

_SYSTEM = """\
You are a research synthesizer. Write a comprehensive answer to the research \
question using ONLY the verified evidence provided below. Do not add any facts \
that are not supported by the evidence.

Formatting rules:
- Answer the question directly in the first paragraph.
- Cite sources using bracket notation: [src_id].
- Distinguish between verified facts and your inference.
- When sources disagree, report both positions and note the disagreement.
- Disclose any remaining uncertainties or gaps in the evidence.
- Keep the answer well-structured with clear sections if the topic is complex.
- Do NOT invent citations or facts not present in the evidence.\
"""


def synthesize(
    client: OpenAI,
    model: str,
    task: ResearchTask,
    store: EvidenceStore,
    verifications: list[VerificationResult],
) -> str:
    """Produce a draft answer grounded in collected evidence."""
    parts = [
        f"Research question: {task.user_question}\n",
        f"Objective: {task.research_objective}\n",
        "--- EVIDENCE ---\n",
        store.claims_summary(),
    ]

    if verifications:
        parts.append("\n--- VERIFICATION STATUS ---")
        for v in verifications:
            supporting = ", ".join(v.supporting_source_ids) if v.supporting_source_ids else "none"
            parts.append(
                f"- [{v.status.upper()}] {v.claim_text}  "
                f"(supported by: {supporting})"
            )
            if v.notes:
                parts.append(f"  Note: {v.notes}")

    parts.append("\n--- SOURCE LIST ---")
    for src_info in store.to_citation_list():
        parts.append(f"- {src_info['id']}: {src_info['title']} ({src_info['url']})")

    return llm_call(client, model, _SYSTEM, "\n".join(parts))
