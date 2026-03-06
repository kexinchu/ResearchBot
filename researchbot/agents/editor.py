"""Editor: structural fixes + style polish. Prompt from skills/editor/SKILL.md."""
import json


def _load_prompt() -> str:
    from researchbot.tools.skills_loader import get_skill_prompt
    return get_skill_prompt("editor")


def run(input_data: dict) -> dict:
    """
    Input: sections (from writer output), contribution_statement, paper_title
    Output: { "sections": { ... } } structurally fixed and polished
    """
    sections = input_data.get("sections") or {}
    contribution_statement = input_data.get("contribution_statement") or ""
    paper_title = input_data.get("paper_title") or ""

    system = _load_prompt()
    user = (
        f"Paper title: {paper_title}\n"
        f"Contribution statement (abstract must reflect this): {contribution_statement}\n\n"
        f"LaTeX sections (JSON):\n{json.dumps(sections, indent=2)}\n\n"
        "Apply all structural checks (abstract 5 elements, related_work grouping, results with [EVID:] tags) "
        "and style rules. Output valid JSON with key 'sections' only. "
        "Preserve [CITE:...], [EVID:...], [SPEC] tags exactly."
    )
    from researchbot.tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True, max_tokens=8192)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {"sections": sections}
    out_sections = out.get("sections") or sections
    for key in ["abstract", "intro", "background", "method", "experiments",
                "results", "related_work", "limitations", "conclusion"]:
        if key not in out_sections:
            out_sections[key] = sections.get(key, "")
    return {"sections": out_sections}
