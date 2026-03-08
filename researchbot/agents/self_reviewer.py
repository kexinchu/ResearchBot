"""Self-Reviewer: systematic paper quality self-review with 6-item checklist."""
import json


def _load_prompt() -> str:
    from researchbot.tools.skills_loader import get_skill_prompt
    return get_skill_prompt("self_reviewer")


def run(input_data: dict) -> dict:
    """
    Input: sections, contribution_statement, annotated_bib, venue
    Output: {
        review_result: {
            overall_score, overall_assessment, checklist, critical_issues, fix_list
        }
    }
    """
    sections = input_data.get("sections") or {}
    contribution_statement = input_data.get("contribution_statement") or ""
    venue = input_data.get("venue") or ""
    annotated_bib = input_data.get("annotated_bib") or []

    # Compact bib for context
    bib_compact = [
        {"key": b.get("key", ""), "title": b.get("title", "")}
        for b in annotated_bib[:30] if isinstance(b, dict) and b.get("key")
    ]

    system = _load_prompt()
    user = (
        f"Target venue: {venue}\n"
        f"Contribution statement: {contribution_statement}\n\n"
        f"Annotated bib keys:\n{json.dumps(bib_compact, indent=2)}\n\n"
        f"Paper sections:\n{json.dumps(sections, indent=2, ensure_ascii=False)}\n\n"
        "Conduct a systematic self-review using the 6-item quality checklist. "
        "Score each item 0-5 and provide specific, actionable issues and suggestions. "
        "Output valid JSON only, matching the format in your instructions."
    )

    from researchbot.tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True, max_tokens=4096)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}

    review = out.get("review_result") or {}
    if not review.get("overall_score"):
        # Calculate from checklist if available
        checklist = review.get("checklist") or {}
        scores = [v.get("score", 0) for v in checklist.values() if isinstance(v, dict)]
        review["overall_score"] = round(sum(scores) / max(len(scores), 1), 1)

    if not review.get("overall_assessment"):
        score = review.get("overall_score", 0)
        if score >= 4:
            review["overall_assessment"] = "ready_for_review"
        elif score >= 3:
            review["overall_assessment"] = "needs_minor_fixes"
        else:
            review["overall_assessment"] = "needs_major_revision"

    return {"review_result": review}
