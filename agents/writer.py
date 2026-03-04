"""Writer: workshop LaTeX draft. Prompt from skills/writer/SKILL.md."""
import json


def _load_prompt() -> str:
    from tools.skills_loader import get_skill_prompt
    return get_skill_prompt("writer")


def run(input_data: dict) -> dict:
    """
    Input: topic, venue, paper_title, contribution_statement, contribution_type,
           method_outline, annotated_bib, related_work_draft, hypotheses,
           skeptic_output, experiment_output, fix_list
    Output: { "sections": { abstract, intro, ..., conclusion } }
    """
    topic = input_data.get("topic", "")
    venue = input_data.get("venue", "")
    paper_title = input_data.get("paper_title") or topic
    contribution_statement = input_data.get("contribution_statement") or ""
    contribution_type = input_data.get("contribution_type") or "empirical"
    method_outline = input_data.get("method_outline", "")
    bib = input_data.get("annotated_bib", [])
    related_work_draft = input_data.get("related_work_draft") or ""
    hypotheses = input_data.get("hypotheses", [])
    skeptic = input_data.get("skeptic_output") or {}
    experiment_output = input_data.get("experiment_output") or {}
    fix_list = input_data.get("fix_list") or []

    system = _load_prompt()
    user = (
        f"Paper title: {paper_title}\n"
        f"Topic: {topic}\nVenue: {venue}\n"
        f"Contribution type: {contribution_type}\n"
        f"Contribution statement: {contribution_statement}\n\n"
        f"Method outline:\n{method_outline}\n\n"
        f"Annotated bib (use [CITE:key] with these exact keys):\n{json.dumps(bib, indent=2)}\n\n"
        f"Related work draft (use as base for related_work section):\n{related_work_draft}\n\n"
        f"Hypotheses:\n{json.dumps(hypotheses, indent=2)}\n\n"
        f"Skeptic review (address rejection_risks in method/experiments/limitations):\n{json.dumps(skeptic, indent=2)}\n\n"
        f"Experiment results (use [EVID:exp_N] / [EVID:ablation_N] tags):\n{json.dumps(experiment_output, indent=2)}\n\n"
    )
    if fix_list:
        user += "IMPORTANT – fix required from previous iteration:\n"
        user += "\n".join(f"- {f}" for f in fix_list) + "\n\n"
    user += (
        "Output valid JSON with key 'sections' only. "
        "Each section must contain substantive paragraph text (minimum 3 full sentences). "
        "Use [CITE:key] for citations, [EVID:exp_N] for experiment references, [SPEC] sparingly."
    )

    from tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True, max_tokens=4096)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}

    sections = out.get("sections") or {}
    for key in ["abstract", "intro", "background", "method", "experiments",
                "results", "related_work", "limitations", "conclusion"]:
        if key not in sections:
            sections[key] = ""
    return {"sections": sections}
