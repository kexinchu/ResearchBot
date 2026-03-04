"""Ideator: generates paper_title, contribution_statement, and falsifiable hypotheses."""
import json


def _load_prompt() -> str:
    from tools.skills_loader import get_skill_prompt
    return get_skill_prompt("ideator")


def run(input_data: dict) -> dict:
    """
    Input: topic, venue, constraints
    Output: {
        paper_title, contribution_statement, contribution_type,
        hypotheses: [HypothesisCard, ...]
    }
    """
    topic = input_data.get("topic", "")
    venue = input_data.get("venue", "")
    constraints = input_data.get("constraints", "")
    fix_list = input_data.get("fix_list") or []

    system = _load_prompt()
    user = f"Topic: {topic}\nVenue: {venue}\nConstraints: {constraints}\n\n"
    if fix_list:
        user += "IMPORTANT – fix required from previous attempt:\n"
        user += "\n".join(f"- {f}" for f in fix_list) + "\n\n"
    user += (
        "Output valid JSON only. Required top-level keys: "
        "paper_title, contribution_statement, contribution_type, hypotheses (array of 3-10 objects)."
    )

    from tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True, max_tokens=2048)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}

    hypotheses = out.get("hypotheses") or []
    cards = []
    for i, h in enumerate(hypotheses):
        if isinstance(h, dict):
            cards.append({
                "id": h.get("id") or f"H{i+1}",
                "claim": h.get("claim", ""),
                "falsifiable_test": h.get("falsifiable_test", ""),
                "minimal_experiment": h.get("minimal_experiment", ""),
                "expected_gain": h.get("expected_gain", ""),
                "risks": h.get("risks", ""),
            })

    return {
        "paper_title": out.get("paper_title") or f"Research on {topic}",
        "contribution_statement": out.get("contribution_statement") or "",
        "contribution_type": out.get("contribution_type") or "empirical",
        "hypotheses": cards,
    }
