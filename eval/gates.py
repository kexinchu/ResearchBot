"""Quality gates: PASS/FAIL with reasons."""
import re
from typing import Any, Dict, List

def _count_tag(text: str, tag: str) -> int:
    return len(re.findall(re.escape(tag), text))


def _min_word_count(text: str) -> int:
    """Rough word count."""
    return len(text.split())


def citation_coverage(sections: Dict[str, str], threshold: float = 0.8):
    lit_text = (sections.get("related_work") or "") + (sections.get("intro") or "")
    if not lit_text.strip():
        return True, []
    cite = _count_tag(lit_text, "[CITE:")
    evid = _count_tag(lit_text, "[EVID:")
    spec = _count_tag(lit_text, "[SPEC]")
    total = cite + evid + spec
    if total == 0:
        # Sections have text but zero tags — this is a failure
        return False, ["No [CITE:...] or [EVID:...] or [SPEC] tags in intro/related_work."]
    coverage = (cite + evid) / total
    reasons = [] if coverage >= threshold else ["citation_coverage < {} in intro/related_work".format(threshold)]
    return coverage >= threshold, reasons


def speculation_ratio(sections: Dict[str, str], threshold: float = 0.2):
    text = (sections.get("intro") or "") + (sections.get("method") or "")
    if not text.strip():
        return True, []
    cite = _count_tag(text, "[CITE:")
    evid = _count_tag(text, "[EVID:")
    spec = _count_tag(text, "[SPEC]")
    total = cite + evid + spec
    if total == 0:
        # Intro+method have content but no tags at all — fail (not grounded)
        word_count = _min_word_count(text)
        if word_count > 50:
            return False, ["No [CITE:] or [EVID:] or [SPEC] tags in intro/method — claims are ungrounded."]
        return True, []
    ratio = spec / total
    reasons = [] if ratio <= threshold else ["speculation_ratio > {} in intro/method".format(threshold)]
    return ratio <= threshold, reasons


def baseline_checklist(baseline_checklist: List[str], min_baselines: int = 1):
    n = len(baseline_checklist) if baseline_checklist else 0
    reasons = [] if n >= min_baselines else ["baseline_checklist has < {} items".format(min_baselines)]
    return n >= min_baselines, reasons


def _item_mentioned(item: str, text: str) -> bool:
    """Check if a Skeptic item is addressed in the text via keyword overlap."""
    text_lower = text.lower()
    # Extract significant words (length >= 4) from the item
    words = re.findall(r'\b\w{4,}\b', item.lower())
    if not words:
        return False
    # Item is "mentioned" if >= 1/3 of its keywords appear in the text (min 1)
    threshold = max(1, len(words) // 3)
    matches = sum(1 for w in words if w in text_lower)
    return matches >= threshold


def skeptic_items_closed(skeptic_output: Dict[str, Any], writer_sections: Dict[str, str], close_ratio: float = 0.5):
    req_exp = skeptic_output.get("required_experiments") or []
    rej = skeptic_output.get("rejection_risks") or []
    items = req_exp + rej
    if not items:
        return True, []
    text = (
        (writer_sections.get("method") or "")
        + (writer_sections.get("experiments") or "")
        + (writer_sections.get("limitations") or "")
        + (writer_sections.get("results") or "")
    )
    mentioned = sum(1 for item in items if item and _item_mentioned(item, text))
    ratio = mentioned / len(items)
    reasons = [] if ratio >= close_ratio else [
        f"skeptic_items_closed {mentioned}/{len(items)} < {close_ratio}"
    ]
    return ratio >= close_ratio, reasons


def experiment_evidence_coverage(sections: Dict[str, str], experimenter_output: Dict[str, Any], threshold: float = 0.5):
    """Check that results/experiments sections reference experiment results with [EVID:...] tags."""
    exp_plans = experimenter_output.get("experiment_plan") or []
    if not exp_plans:
        return True, []
    text = (sections.get("results") or "") + (sections.get("experiments") or "")
    evid_count = len(re.findall(r"\[EVID:[^\]]+\]", text))
    needed = max(1, len(exp_plans) * threshold)
    ok = evid_count >= needed
    reasons = [] if ok else [f"Only {evid_count} [EVID:...] tags in results/experiments, expected >= {needed:.0f}"]
    return ok, reasons


def abstract_completeness(sections: Dict[str, str]) -> tuple:
    """Check that the abstract contains all five required elements."""
    abstract = sections.get("abstract") or ""
    if len(abstract.strip()) < 50:
        return False, ["abstract is missing or too short (< 50 chars)"]
    reasons = []
    if not re.search(r"\[EVID:[^\]]+\]", abstract):
        reasons.append("abstract missing [EVID:exp_N] tag (no numeric result cited)")
    if not re.search(r"\[CITE:[^\]]+\]|\[EVID:[^\]]+\]", abstract):
        reasons.append("abstract has no [CITE:key] or [EVID:exp_N] tags — not grounded in evidence")
    ok = len(reasons) == 0
    return ok, reasons


def cite_key_validity(sections: Dict[str, str], annotated_bib: List[Dict[str, Any]]) -> tuple:
    """Check that all [CITE:key] tags reference keys that exist in annotated_bib."""
    if not annotated_bib:
        return True, []
    valid_keys = {b.get("key") for b in annotated_bib if b.get("key")}
    all_text = " ".join(str(v) for v in sections.values())
    used_keys = set(re.findall(r"\[CITE:([^\]]+)\]", all_text))
    invalid = used_keys - valid_keys
    reasons = [f"[CITE:{k}] not found in annotated_bib" for k in sorted(invalid)]
    return len(invalid) == 0, reasons


def section_minimum_length(sections: Dict[str, str], min_words: int = 30) -> tuple:
    """Check that critical sections have minimum content length."""
    critical = ["abstract", "intro", "method", "experiments", "results", "conclusion"]
    reasons = []
    for key in critical:
        text = sections.get(key) or ""
        wc = _min_word_count(text)
        if wc < min_words:
            reasons.append(f"Section '{key}' too short ({wc} words, minimum {min_words})")
    return len(reasons) == 0, reasons


def run_gates(
    stage: str,
    state: Dict[str, Any],
    citation_threshold: float = 0.8,
    speculation_threshold: float = 0.2,
    min_baselines: int = 1,
    skeptic_close_ratio: float = 0.5,
) -> tuple:
    all_passed = True
    reasons = []
    if stage in ("writer", "editor"):
        sections = (state.get("editor_output") or state.get("writer_output") or {}).get("sections") or {}
        deep = state.get("deep_research_output") or {}
        skeptic = state.get("skeptic_output") or {}
        experimenter = state.get("experimenter_output") or {}

        for gate_fn, args in [
            (citation_coverage,            (sections, citation_threshold)),
            (speculation_ratio,            (sections, speculation_threshold)),
            (baseline_checklist,           (deep.get("baseline_checklist", []), min_baselines)),
            (skeptic_items_closed,         (skeptic, sections, skeptic_close_ratio)),
            (experiment_evidence_coverage, (sections, experimenter)),
            (abstract_completeness,        (sections,)),
            (cite_key_validity,            (sections, deep.get("annotated_bib", []))),
            (section_minimum_length,       (sections,)),
        ]:
            ok, r = gate_fn(*args)
            if not ok:
                all_passed = False
                reasons.extend(r)
    return all_passed, reasons
