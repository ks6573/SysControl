"""Claim extractor — uses the LLM to pull structured claims from source text."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from openai import OpenAI

from deep_research.config import llm_json
from deep_research.schemas import Claim, ResearchTask, Source

_SYSTEM = """\
You are an evidence extraction assistant. Given a source text and a research \
question, extract key factual claims that are relevant to the question.

Return ONLY valid JSON:
{
  "source_type": "official" | "news" | "paper" | "blog" | "forum" | "dataset",
  "publisher": "name of the publishing organization if identifiable",
  "published_at": "date if found in the text, else empty string",
  "claims": [
    {
      "text": "a specific factual claim from the source",
      "support_type": "direct" | "partial" | "uncertain",
      "quote": "relevant verbatim quote (keep short, max ~50 words)",
      "extracted_data": {"date": "...", "number": "..."}
    }
  ]
}

Guidelines:
- Extract 2-8 claims per source — focus on facts, figures, and dates.
- "direct" = the source explicitly states this as fact.
- "partial" = the source implies or partially supports this.
- "uncertain" = the claim is mentioned but not well-supported.
- Ignore boilerplate, navigation text, ads, and irrelevant content.
- If the source text is too short or irrelevant, return an empty claims list.\
"""


@dataclass
class ExtractionResult:
    """Claims plus source metadata extracted by the LLM."""

    claims: list[Claim]
    source_type: str = "unknown"
    publisher: str = ""
    published_at: str = ""


_MAX_EXTRACTION_CHARS = 5000


def extract_claims(
    client: OpenAI,
    model: str,
    task: ResearchTask,
    source: Source,
) -> ExtractionResult:
    """Extract structured claims and metadata from a source's raw text.

    Returns an ``ExtractionResult`` — the caller is responsible for applying
    metadata updates to the source object.
    """
    text = source.raw_text[:_MAX_EXTRACTION_CHARS]

    user_prompt = (
        f"Research question: {task.research_objective}\n\n"
        f"Source URL: {source.url}\n"
        f"Source title: {source.title}\n\n"
        f"Source text:\n{text}"
    )

    data = llm_json(client, model, _SYSTEM, user_prompt)

    claims: list[Claim] = []
    for item in data.get("claims", []):
        claim_text = item.get("text", "").strip()
        if not claim_text:
            continue
        claims.append(
            Claim(
                claim_id=f"claim_{uuid.uuid4().hex[:8]}",
                text=claim_text,
                support_type=item.get("support_type", "uncertain"),
                quote=item.get("quote", ""),
                extracted_data=item.get("extracted_data", {}),
            )
        )

    return ExtractionResult(
        claims=claims,
        source_type=data.get("source_type", "unknown"),
        publisher=data.get("publisher", ""),
        published_at=data.get("published_at", ""),
    )
