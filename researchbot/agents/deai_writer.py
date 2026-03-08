"""De-AI Writer: removes AI-generated writing patterns from paper sections."""
import json


def _load_prompt() -> str:
    from researchbot.tools.skills_loader import get_skill_prompt
    return get_skill_prompt("deai_writer")


def run(input_data: dict) -> dict:
    """
    Input: sections (from editor output)
    Output: { "sections": { abstract, intro, ..., conclusion } } with AI patterns removed
    """
    sections = input_data.get("sections") or {}

    system = _load_prompt()
    user = (
        "Remove AI-generated writing patterns from the following academic paper sections. "
        "Make the text sound natural and human-written while preserving all technical content, "
        "citation tags [CITE:key], evidence tags [EVID:exp_N], and speculation tags [SPEC].\n\n"
        f"Paper sections (JSON):\n{json.dumps(sections, indent=2, ensure_ascii=False)}\n\n"
        "Apply all five core rules: cut filler phrases, break formulaic structures, "
        "vary rhythm, trust readers, use precise academic language. "
        "Output valid JSON with key 'sections' only. Preserve all tags exactly."
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
