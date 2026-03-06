"""Writer: workshop LaTeX draft. Prompt from skills/writer/SKILL.md."""
import json


def _load_prompt() -> str:
    from tools.skills_loader import get_skill_prompt
    return get_skill_prompt("writer")


def _truncate_bib(bib: list, max_entries: int = 20) -> list:
    """Keep only the most useful fields per bib entry and cap total entries."""
    out = []
    for b in bib[:max_entries]:
        if not isinstance(b, dict):
            continue
        out.append({
            "key": b.get("key", ""),
            "title": b.get("title", ""),
            "contribution": (b.get("contribution") or "")[:200],
            "year": b.get("year", ""),
        })
    return out


def _truncate_experiment(exp: dict, max_chars: int = 3000) -> dict:
    """Keep experiment_plan and result_summary, drop verbose fields like code_snippets."""
    if not exp:
        return {}
    out = {
        "experiment_plan": exp.get("experiment_plan") or [],
        "result_tables": exp.get("result_tables") or [],
        "result_summary": (exp.get("result_summary") or "")[:1000],
    }
    dumped = json.dumps(out, ensure_ascii=False)
    if len(dumped) > max_chars:
        # Further truncate experiment_plan
        plans = out["experiment_plan"]
        for p in plans:
            if isinstance(p, dict):
                for k in ("procedure", "setup"):
                    if k in p:
                        p[k] = str(p[k])[:200] + "…"
    return out


def run(input_data: dict) -> dict:
    """
    Input: topic, venue, paper_title, contribution_statement, contribution_type,
           method_outline, annotated_bib, related_work_draft, hypotheses,
           skeptic_output, experiment_output, fix_list,
           sections_to_write (optional), existing_sections (optional)
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
    sections_to_write = input_data.get("sections_to_write") or []
    existing_sections = input_data.get("existing_sections") or {}

    # Truncate large inputs to prevent context overflow
    bib_compact = _truncate_bib(bib)
    exp_compact = _truncate_experiment(experiment_output)
    # Skeptic: keep only the essential fields
    skeptic_compact = {
        "contribution_statement": skeptic.get("contribution_statement", ""),
        "novelty_verdict": skeptic.get("novelty_verdict", ""),
        "rejection_risks": (skeptic.get("rejection_risks") or [])[:8],
        "required_experiments": (skeptic.get("required_experiments") or [])[:6],
    }

    system = _load_prompt()
    user = (
        f"Paper title: {paper_title}\n"
        f"Topic: {topic}\nVenue: {venue}\n"
        f"Contribution type: {contribution_type}\n"
        f"Contribution statement: {contribution_statement}\n\n"
        f"Method outline:\n{method_outline}\n\n"
        f"Annotated bib (use [CITE:key] with these exact keys):\n{json.dumps(bib_compact, indent=2)}\n\n"
        f"Related work draft (use as base for related_work section):\n{related_work_draft}\n\n"
        f"Hypotheses:\n{json.dumps(hypotheses, indent=2)}\n\n"
        f"Skeptic review (address rejection_risks in method/experiments/limitations):\n{json.dumps(skeptic_compact, indent=2)}\n\n"
        f"Experiment results (use [EVID:exp_N] / [EVID:ablation_N] tags):\n{json.dumps(exp_compact, indent=2)}\n\n"
    )
    if sections_to_write and existing_sections:
        user += (
            "PARTIAL REWRITE MODE: You must ONLY write/regenerate the following sections: "
            + ", ".join(sections_to_write) + ".\n\n"
            "The following sections are FIXED — do NOT change them; they are provided for context only. "
            "Your JSON output must include ONLY the sections you are regenerating ("
            + ", ".join(sections_to_write) + "). "
            "The caller will merge with the fixed sections.\n\n"
            "Existing (fixed) sections for context:\n"
            + json.dumps({k: (existing_sections.get(k) or "")[:800] + ("..." if len((existing_sections.get(k) or "")) > 800 else "") for k in existing_sections}, indent=2, ensure_ascii=False)
            + "\n\n"
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
    raw = call_llm(system, user, json_mode=True, max_tokens=8192)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}

    sections = out.get("sections") or {}
    all_keys = ["abstract", "intro", "background", "method", "experiments",
                "results", "related_work", "limitations", "conclusion"]
    if sections_to_write and existing_sections:
        # Merge: new sections from LLM, rest from existing
        merged = dict(existing_sections)
        for k in sections_to_write:
            if k in sections and sections[k].strip():
                merged[k] = sections[k]
        sections = merged
    for key in all_keys:
        if key not in sections:
            sections[key] = ""
    return {"sections": sections}
