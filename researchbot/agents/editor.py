"""Editor: structural fixes + style polish + anti-AI writing. Prompt from skills/editor/SKILL.md."""
import json


def _load_prompt() -> str:
    from researchbot.tools.skills_loader import get_skill_prompt
    return get_skill_prompt("editor")


def run(input_data: dict) -> dict:
    """
    Input: sections (from writer output), contribution_statement, paper_title, skeptic_output (optional)
    Output: { "sections": { ... } } structurally fixed and polished
    """
    sections = input_data.get("sections") or {}
    contribution_statement = input_data.get("contribution_statement") or ""
    paper_title = input_data.get("paper_title") or ""
    skeptic = input_data.get("skeptic_output") or {}

    system = _load_prompt()

    # Build context block with Skeptic feedback for the Editor
    skeptic_block = ""
    if skeptic:
        risks = skeptic.get("rejection_risks") or []
        threats = skeptic.get("threats_to_validity") or []
        methodology_gaps = skeptic.get("methodology_gaps") or []
        if risks or threats or methodology_gaps:
            skeptic_block = "\nSKEPTIC FEEDBACK (ensure these are addressed in the paper):\n"
            if risks:
                skeptic_block += f"  Rejection risks: {json.dumps(risks)}\n"
            if threats:
                skeptic_block += f"  Threats to validity: {json.dumps(threats)}\n"
            if methodology_gaps:
                skeptic_block += f"  Methodology gaps: {json.dumps(methodology_gaps)}\n"

    user = (
        f"Paper title: {paper_title}\n"
        f"Contribution statement (abstract must reflect this): {contribution_statement}\n"
        f"{skeptic_block}\n"
        f"LaTeX sections (JSON):\n{json.dumps(sections, indent=2)}\n\n"
        "Apply all structural checks (abstract 5 elements, related_work grouping, results with [EVID:] tags), "
        "results presentation rules (claim-evidence-interpretation pattern), "
        "and anti-AI style rules. Output valid JSON with key 'sections' only. "
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
