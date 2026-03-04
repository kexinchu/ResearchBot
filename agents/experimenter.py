"""Experimenter: design experiments, generate code scaffolds, produce simulated result tables.
Prompt from skills/experimenter/SKILL.md."""
import json


def _load_prompt() -> str:
    from tools.skills_loader import get_skill_prompt
    return get_skill_prompt("experimenter")


def run(input_data: dict) -> dict:
    """
    Input: hypotheses, deep_research_output, skeptic_output
    Output: experiment_plan, code_snippets, result_tables, result_summary
    """
    hypotheses = input_data.get("hypotheses", [])
    contribution_statement = input_data.get("contribution_statement") or ""
    contribution_type = input_data.get("contribution_type") or "empirical"
    deep = input_data.get("deep_research_output") or {}
    skeptic = input_data.get("skeptic_output") or {}

    system = _load_prompt()
    user = (
        f"Contribution statement (design exp_1 to directly test this claim):\n{contribution_statement}\n"
        f"Contribution type: {contribution_type}\n\n"
        f"Selected hypotheses:\n{json.dumps(hypotheses, indent=2)}\n\n"
        f"Deep research output:\n"
        f"  annotated_bib (use realistic numbers from snippets as reference):\n"
        f"    {json.dumps(deep.get('annotated_bib', []), indent=2)}\n"
        f"  baseline_checklist: {json.dumps(deep.get('baseline_checklist', []), indent=2)}\n"
        f"  metrics_checklist: {json.dumps(deep.get('metrics_checklist', []), indent=2)}\n"
        f"  gap_summary: {deep.get('gap_summary', '')}\n\n"
        f"Skeptic output:\n"
        f"  required_experiments: {json.dumps(skeptic.get('required_experiments', []), indent=2)}\n"
        f"  rejection_risks: {json.dumps(skeptic.get('rejection_risks', []), indent=2)}\n\n"
        "IMPORTANT: Follow the realistic improvement margin and statistical notation rules in your instructions.\n"
        "Output valid JSON only."
    )
    from tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}
    return {
        "experiment_plan": out.get("experiment_plan") or [],
        "code_snippets": out.get("code_snippets") or {},
        "result_tables": out.get("result_tables") or [],
        "result_summary": out.get("result_summary") or "",
    }
