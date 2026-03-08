"""Ideator: generates paper_title, contribution_statement, and falsifiable hypotheses."""
import json


def _load_prompt() -> str:
    from researchbot.tools.skills_loader import get_skill_prompt
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
    retrieved_memory = input_data.get("retrieved_memory") or ""
    preferred_focus = (input_data.get("preferred_focus") or "").strip().lower()

    system = _load_prompt()
    user = f"Topic: {topic}\nVenue: {venue}\nConstraints: {constraints}\n\n"
    if preferred_focus in ("system", "theory", "empirical", "analysis"):
        _focus_guidance = {
            "system": "Preferred focus: SYSTEM. Set contribution_type to 'system'. Propose hypotheses about system design, architecture, algorithms, or performance (e.g. latency, throughput, scalability, resource efficiency). Avoid purely theoretical or pure-applied-empirical angles; emphasize what the system does and how it improves over prior systems.",
            "theory": "Preferred focus: THEORY. Set contribution_type to 'theory'. Propose hypotheses about bounds, proofs, or formal analysis.",
            "empirical": "Preferred focus: EMPIRICAL. Set contribution_type to 'empirical'. Propose hypotheses testable by benchmarks, ablations, or measurement studies.",
            "analysis": "Preferred focus: ANALYSIS. Set contribution_type to 'analysis'. Propose hypotheses suited to survey, meta-analysis, or replication.",
        }
        user += _focus_guidance.get(preferred_focus, "") + "\n\n"
    if retrieved_memory.strip():
        user += "Relevant context from past runs (use for inspiration only; do not copy verbatim):\n" + retrieved_memory.strip() + "\n\n"
    if fix_list:
        user += "IMPORTANT – fix required from previous attempt:\n"
        user += "\n".join(f"- {f}" for f in fix_list) + "\n\n"
    user += (
        "Output valid JSON only. Required top-level keys: "
        "related_work_summary, gap_analysis (array of objects with type/gap/opportunity/feasibility), "
        "unsolved_problems, research_worthy, proposals, "
        "paper_title, contribution_statement, contribution_type, hypotheses (array of 3-8 objects)."
    )

    from researchbot.tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True, max_tokens=4096)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}
    if not isinstance(out, dict):
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

    def _norm_list(key: str, item_keys: list) -> list:
        lst = out.get(key) or []
        if not isinstance(lst, list):
            return []
        return [x for x in lst if isinstance(x, dict) and any(x.get(k) for k in item_keys)]

    return {
        "related_work_summary": out.get("related_work_summary") or "",
        "gap_analysis": _norm_list("gap_analysis", ["type", "gap", "opportunity"]),
        "unsolved_problems": _norm_list("unsolved_problems", ["problem", "context"]),
        "research_worthy": _norm_list("research_worthy", ["problem", "rationale"]),
        "proposals": _norm_list("proposals", ["motivation", "idea", "challenges"]),
        "paper_title": out.get("paper_title") or f"Research on {topic}",
        "contribution_statement": out.get("contribution_statement") or "",
        "contribution_type": out.get("contribution_type") or "empirical",
        "hypotheses": cards,
    }
