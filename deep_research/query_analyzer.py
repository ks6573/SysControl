"""Query analysis — decompose a user question into a structured research task."""

from __future__ import annotations

from openai import OpenAI

from deep_research.config import llm_json
from deep_research.schemas import ResearchTask

_SYSTEM = """\
You are a research planning assistant. Analyze the user's question and produce \
a structured JSON object that decomposes it into a research task.

Return ONLY valid JSON with these fields:
{
  "research_objective": "one-sentence restatement of what needs to be answered",
  "subquestions": ["list of 3-7 specific subquestions to investigate"],
  "needs_current_info": true or false,
  "required_output_format": "detailed" or "brief" or "comparison" or "list",
  "constraints": ["any limitations noted in the question"],
  "success_criteria": ["what counts as a sufficient answer"]
}

Guidelines:
- Subquestions should cover: definitions, background, current facts, \
quantitative data, conflicting viewpoints, and edge cases.
- Set needs_current_info=true if the answer could change over time.
- Be specific — vague subquestions produce vague research.\
"""


def analyze_query(client: OpenAI, model: str, question: str) -> ResearchTask:
    """Convert a raw user question into a structured ``ResearchTask``."""
    data = llm_json(client, model, _SYSTEM, question)

    return ResearchTask(
        user_question=question,
        research_objective=data.get("research_objective", question),
        subquestions=data.get("subquestions", [question]),
        needs_current_info=data.get("needs_current_info", True),
        required_output_format=data.get("required_output_format", "detailed"),
        constraints=data.get("constraints", []),
        success_criteria=data.get("success_criteria", []),
    )
