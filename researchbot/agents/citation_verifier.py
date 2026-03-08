"""Citation Verifier: validates all citations in paper sections against annotated_bib."""
import json
import re


def _load_prompt() -> str:
    from researchbot.tools.skills_loader import get_skill_prompt
    return get_skill_prompt("citation_verifier")


def run(input_data: dict) -> dict:
    """
    Input: sections (from writer/editor output), annotated_bib
    Output: {
        verification_results: { total_citations, verified, issues_found, ... },
        issues: [ { severity, type, key, location, description, suggestion } ],
        fixed_bib: [ { key, title, year, contribution, status } ]
    }
    """
    sections = input_data.get("sections") or {}
    annotated_bib = input_data.get("annotated_bib") or []

    system = _load_prompt()

    # Build compact bib for context
    bib_compact = []
    for b in annotated_bib[:50]:
        if isinstance(b, dict):
            bib_compact.append({
                "key": b.get("key", ""),
                "title": b.get("title", ""),
                "year": b.get("year", ""),
                "contribution": (b.get("contribution") or "")[:300],
            })

    user = (
        "Verify all citations in the following paper sections against the annotated bibliography.\n\n"
        f"Annotated bibliography:\n{json.dumps(bib_compact, indent=2)}\n\n"
        f"Paper sections:\n{json.dumps(sections, indent=2, ensure_ascii=False)}\n\n"
        "Check every [CITE:key] tag against the bib. Identify orphan keys, "
        "suspicious entries, misattributions, and unused bib entries. "
        "Output valid JSON only, matching the format in your instructions."
    )

    from researchbot.tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True, max_tokens=4096)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}

    # Also do a programmatic check for orphan keys
    all_text = " ".join(str(v) for v in sections.values())
    used_keys = set(re.findall(r"\[CITE:([^\]]+)\]", all_text))
    bib_keys = {b.get("key") for b in annotated_bib if b.get("key")}
    orphan_keys = used_keys - bib_keys
    unused_keys = bib_keys - used_keys

    # Merge programmatic results with LLM results
    verification = out.get("verification_results") or {}
    verification["total_citations"] = len(used_keys)
    verification["orphan_keys"] = list(orphan_keys | set(verification.get("orphan_keys") or []))
    verification["unused_keys"] = list(unused_keys | set(verification.get("unused_keys") or []))
    verification["issues_found"] = len(out.get("issues") or []) + len(orphan_keys)

    if orphan_keys and not verification.get("overall_status"):
        verification["overall_status"] = "fail"
    elif not verification.get("overall_status"):
        verification["overall_status"] = "pass" if not out.get("issues") else "warn"

    # Add programmatic orphan issues
    issues = out.get("issues") or []
    existing_keys = {i.get("key") for i in issues}
    for key in orphan_keys:
        if key not in existing_keys:
            issues.append({
                "severity": "CRITICAL",
                "type": "orphan",
                "key": key,
                "location": "multiple",
                "description": f"[CITE:{key}] used in text but key not found in annotated_bib",
                "suggestion": f"Add '{key}' to annotated_bib or remove the citation",
            })

    return {
        "verification_results": verification,
        "issues": issues,
        "fixed_bib": out.get("fixed_bib") or [],
    }
