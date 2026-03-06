"""Skeptic: contribution clarification + adversarial review. Prompt from skills/skeptic/SKILL.md."""
import json


def _load_prompt() -> str:
    from researchbot.tools.skills_loader import get_skill_prompt
    return get_skill_prompt("skeptic")


def run(input_data: dict) -> dict:
    """
    Input: approach_summary, deep_research_output, hypotheses, contribution_statement
    Output: contribution_statement, novelty_verdict, rejection_risks, required_experiments, threats_to_validity
    """
    approach = input_data.get("approach_summary", "")
    evidence = input_data.get("deep_research_output") or {}
    hypotheses = input_data.get("hypotheses", [])
    contribution_statement = input_data.get("contribution_statement") or ""

    system = _load_prompt()
    user = (
        f"Contribution statement (from Ideator):\n{contribution_statement}\n\n"
        f"Approach summary:\n{approach}\n\n"
        f"Deep research evidence:\n{json.dumps(evidence, indent=2)}\n\n"
        f"Hypotheses:\n{json.dumps(hypotheses, indent=2)}\n\n"
        "Output valid JSON only."
    )
    from researchbot.tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True, max_tokens=4096)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}
    # Validate novelty_verdict to one of the expected values
    verdict = out.get("novelty_verdict") or "unclear"
    if verdict not in ("clear", "unclear", "missing"):
        verdict = "unclear"
    return {
        "contribution_statement": out.get("contribution_statement") or contribution_statement,
        "novelty_verdict":        verdict,
        "rejection_risks":        out.get("rejection_risks") or [],
        "required_experiments":   out.get("required_experiments") or [],
        "threats_to_validity":    out.get("threats_to_validity") or [],
    }
