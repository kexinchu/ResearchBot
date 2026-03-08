"""Rebuttal Writer: generates structured rebuttals from reviewer feedback."""
import json


def _load_prompt() -> str:
    from researchbot.tools.skills_loader import get_skill_prompt
    return get_skill_prompt("rebuttal_writer")


def run(input_data: dict) -> dict:
    """
    Input: reviewer_outputs, sections, contribution_statement, experimenter_output
    Output: {
        rebuttal: {
            summary, reviewer_responses, new_experiments, paper_revision_summary
        }
    }
    """
    reviewer_outputs = input_data.get("reviewer_outputs") or []
    sections = input_data.get("sections") or {}
    contribution_statement = input_data.get("contribution_statement") or ""
    experimenter_output = input_data.get("experimenter_output") or {}

    system = _load_prompt()

    # Compact reviewer feedback
    reviews_compact = []
    for r in reviewer_outputs:
        if isinstance(r, dict):
            reviews_compact.append({
                "venue": r.get("venue", ""),
                "overall": r.get("overall", 0),
                "strengths": (r.get("strengths") or [])[:5],
                "weaknesses": (r.get("weaknesses") or [])[:5],
                "required_revisions": (r.get("required_revisions") or [])[:8],
                "recommendation": r.get("recommendation", ""),
            })

    # Compact experiment output
    exp_compact = {
        "experiment_plan": (experimenter_output.get("experiment_plan") or [])[:6],
        "result_summary": (experimenter_output.get("result_summary") or "")[:800],
    }

    user = (
        f"Contribution statement: {contribution_statement}\n\n"
        f"Reviewer feedback:\n{json.dumps(reviews_compact, indent=2, ensure_ascii=False)}\n\n"
        f"Current paper sections (for reference):\n{json.dumps({k: v[:500] + '...' if len(v) > 500 else v for k, v in sections.items()}, indent=2, ensure_ascii=False)}\n\n"
        f"Experiment output (for evidence):\n{json.dumps(exp_compact, indent=2, ensure_ascii=False)}\n\n"
        "Analyze reviewer comments, classify each, develop response strategies, "
        "and write a complete, professional rebuttal document. "
        "Output valid JSON only, matching the format in your instructions."
    )

    from researchbot.tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True, max_tokens=6144)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}

    rebuttal = out.get("rebuttal") or {}
    if not rebuttal.get("summary"):
        rebuttal["summary"] = "Rebuttal generation incomplete — please review manually."

    return {"rebuttal": rebuttal}
