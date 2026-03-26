"""Research planner — generates and refines step-by-step search plans."""

from __future__ import annotations

from openai import OpenAI

from deep_research.config import llm_json
from deep_research.evidence_store import EvidenceStore
from deep_research.schemas import PlanStep, ResearchPlan, ResearchTask, VerificationResult

_SYSTEM = """\
You are a research planner. Given a research task and (optionally) evidence \
collected so far, produce a JSON research plan.

Return ONLY valid JSON:
{
  "steps": [
    {
      "id": "step_1",
      "goal": "what this step aims to find",
      "tool": "web_search",
      "query": "specific search query to run",
      "priority": 1
    }
  ],
  "open_questions": ["questions not yet answered"],
  "verification_targets": ["important claims that need corroboration"]
}

Guidelines:
- Generate 3-6 search steps per plan.
- Each query should be a specific, effective web search string.
- Higher priority = more important (1 is highest).
- Prefer queries that target primary/official sources.
- If evidence already exists, focus on GAPS — unanswered subquestions, \
unverified claims, and contradictions.
- Do NOT repeat searches that have already been done.\
"""


def make_plan(
    client: OpenAI,
    model: str,
    task: ResearchTask,
    store: EvidenceStore,
    verifications: list[VerificationResult],
) -> ResearchPlan:
    """Generate a research plan based on the task and current evidence state."""
    user_parts = [
        f"Research objective: {task.research_objective}",
        f"Subquestions: {task.subquestions}",
    ]

    if store.source_count() > 0:
        user_parts.append(f"\nSources gathered so far: {store.source_count()}")
        user_parts.append(f"Claims collected:\n{store.claims_summary()}")

    if verifications:
        unresolved = [v for v in verifications if v.status != "verified"]
        if unresolved:
            user_parts.append(
                "\nUnresolved claims needing more evidence:\n"
                + "\n".join(f"- [{v.status}] {v.claim_text}" for v in unresolved)
            )

    data = llm_json(client, model, _SYSTEM, "\n".join(user_parts))

    steps = [
        PlanStep(
            id=s.get("id", f"step_{i}"),
            goal=s.get("goal", ""),
            tool=s.get("tool", "web_search"),
            query=s.get("query", ""),
            priority=s.get("priority", i + 1),
        )
        for i, s in enumerate(data.get("steps", []))
        if s.get("query")
    ]

    # Fallback: if the LLM returned no valid steps, generate a basic search.
    if not steps:
        steps = [
            PlanStep(id="fallback_1", goal="General search", query=task.user_question, priority=1),
        ]

    return ResearchPlan(
        steps=steps,
        open_questions=data.get("open_questions", []),
        verification_targets=data.get("verification_targets", []),
    )
