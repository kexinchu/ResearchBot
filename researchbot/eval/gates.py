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
        if word_count > 20:
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
    """Check if a Skeptic item is addressed in the text via keyword overlap.
    Requires at least half of significant keywords to appear (stricter matching)."""
    text_lower = text.lower()
    # Extract significant words (length >= 4) from the item
    words = re.findall(r'\b\w{4,}\b', item.lower())
    # Filter out very common words that don't indicate real addressing
    stopwords = {"this", "that", "with", "from", "have", "been", "will", "should",
                 "could", "would", "more", "than", "also", "each", "such", "very",
                 "does", "what", "when", "where", "which", "about", "into", "only"}
    words = [w for w in words if w not in stopwords]
    if not words:
        return False
    threshold = max(2, len(words) // 2)
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


def ai_writing_patterns(sections: Dict[str, str]) -> tuple:
    """Check for common AI-generated writing patterns."""
    ai_phrases = [
        "delve into", "it is important to note", "it is worth mentioning",
        "in recent years", "it is crucial", "plays a crucial role",
        "stands as a testament", "it is worth noting", "as can be seen",
        "groundbreaking", "revolutionary", "comprehensive framework",
        "robust approach", "leverage", "in the realm of",
    ]
    all_text = " ".join(str(v) for v in sections.values()).lower()
    found = [p for p in ai_phrases if p in all_text]
    if len(found) >= 3:
        return False, [f"AI writing patterns detected ({len(found)}): {', '.join(found[:5])}"]
    return True, []


def limitations_present(sections: Dict[str, str]) -> tuple:
    """Check that the limitations section exists and has content."""
    lim = sections.get("limitations") or ""
    wc = _min_word_count(lim)
    if wc < 20:
        return False, [f"Limitations section too short or missing ({wc} words, minimum 20)"]
    return True, []


def contribution_in_abstract(sections: Dict[str, str], contribution_statement: str) -> tuple:
    """Check that the contribution statement appears in the abstract."""
    if not contribution_statement:
        return True, []
    abstract = (sections.get("abstract") or "").lower()
    # Check for keyword overlap (at least 40% of significant words)
    words = re.findall(r'\b\w{5,}\b', contribution_statement.lower())
    if not words:
        return True, []
    matches = sum(1 for w in words if w in abstract)
    ratio = matches / len(words)
    if ratio < 0.3:
        return False, ["Contribution statement not reflected in abstract (< 30% keyword overlap)"]
    return True, []


def baseline_count(baseline_list: List[str], min_count: int = 3) -> tuple:
    """Check that at least min_count baselines are specified for rigorous comparison."""
    n = len(baseline_list) if baseline_list else 0
    if n < min_count:
        return False, [f"Only {n} baseline(s) specified, minimum {min_count} required for rigorous comparison"]
    return True, []


def results_have_statistics(sections: Dict[str, str]) -> tuple:
    """Check that results section includes statistical reporting elements."""
    results = (sections.get("results") or "") + (sections.get("experiments") or "")
    if not results.strip():
        return True, []
    reasons = []
    # Check for mean +/- std notation
    has_plusminus = bool(re.search(r'±|\\pm|\+/-|plus or minus', results))
    if not has_plusminus:
        reasons.append("Results missing mean±SD/SE notation — add statistical variance to reported numbers")
    # Check for p-value or significance language
    has_significance = bool(re.search(r'p\s*[<>=]\s*0\.\d|statistically significant|significance test|confidence interval', results, re.IGNORECASE))
    if not has_significance:
        reasons.append("Results missing statistical significance language (p-values, confidence intervals)")
    return len(reasons) == 0, reasons


def method_has_formalization(sections: Dict[str, str]) -> tuple:
    """Check that the method section has formal problem definition."""
    method = sections.get("method") or ""
    if _min_word_count(method) < 50:
        return True, []  # Too short to check — section_minimum_length will catch it
    # Look for formal notation markers
    has_formal = bool(re.search(
        r'\\mathcal|\\mathbb|\\in\b|\\forall|\\exists|given\s+.+?,\s+find|'
        r'minimize|maximize|objective|formally|definition|denote|notation|'
        r'let\s+\$|problem\s+formulation|problem\s+statement',
        method, re.IGNORECASE
    ))
    if not has_formal:
        return False, ["Method section missing formal problem definition or notation paragraph"]
    return True, []


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

        contribution_stmt = state.get("contribution_statement") or ""
        for gate_fn, args in [
            (citation_coverage,            (sections, citation_threshold)),
            (speculation_ratio,            (sections, speculation_threshold)),
            (baseline_checklist,           (deep.get("baseline_checklist", []), min_baselines)),
            (baseline_count,               (deep.get("baseline_checklist", []),)),
            (skeptic_items_closed,         (skeptic, sections, skeptic_close_ratio)),
            (experiment_evidence_coverage, (sections, experimenter)),
            (abstract_completeness,        (sections,)),
            (cite_key_validity,            (sections, deep.get("annotated_bib", []))),
            (section_minimum_length,       (sections,)),
            (ai_writing_patterns,          (sections,)),
            (limitations_present,          (sections,)),
            (contribution_in_abstract,     (sections, contribution_stmt)),
            (results_have_statistics,      (sections,)),
            (method_has_formalization,     (sections,)),
        ]:
            ok, r = gate_fn(*args)
            if not ok:
                all_passed = False
                reasons.extend(r)
    return all_passed, reasons


def build_actionable_fix_list(
    gate_reasons: List[str],
    state: Dict[str, Any],
) -> List[str]:
    """Convert gate failure reasons into specific, actionable fix instructions for the Writer.

    Instead of passing raw gate reasons (which are diagnostic), this generates
    concrete instructions with available keys and section targets.
    """
    fixes = []
    deep = state.get("deep_research_output") or {}
    bib = deep.get("annotated_bib") or []
    bib_keys = [b.get("key", "") for b in bib if b.get("key")]
    exp_plans = (state.get("experimenter_output") or {}).get("experiment_plan") or []
    exp_ids = [p.get("id", "") for p in exp_plans if isinstance(p, dict) and p.get("id")]

    joined = " ".join(gate_reasons).lower()

    # Citation/tag issues
    if "no [cite:" in joined or "citation_coverage" in joined:
        keys_hint = ", ".join(bib_keys[:8])
        fixes.append(
            f"Add [CITE:key] tags in intro and related_work sections. "
            f"Available keys: {keys_hint}. Each paragraph in related_work must have at least one [CITE:key]."
        )
    if "not found in annotated_bib" in joined:
        invalid = [r.split("]")[0].replace("[CITE:", "") for r in gate_reasons if "not found" in r]
        fixes.append(
            f"Remove invalid citation keys: {', '.join(invalid[:5])}. "
            f"Only use these keys: {', '.join(bib_keys[:10])}."
        )
    if "no [evid:" in joined or "evid" in joined:
        ids_hint = ", ".join(exp_ids[:6]) if exp_ids else "exp_1, exp_2"
        fixes.append(
            f"Add [EVID:exp_N] tags in results and experiments sections. "
            f"Available experiment IDs: {ids_hint}. Every numerical claim needs an [EVID:] tag."
        )

    # Content quality issues
    if "abstract" in joined and ("missing" in joined or "short" in joined):
        fixes.append(
            "Rewrite abstract with all 5 elements: (1) problem context, (2) gap in prior work, "
            "(3) contribution statement, (4) method summary, (5) key result with [EVID:exp_1]."
        )
    if "too short" in joined:
        short_sections = re.findall(r"section '(\w+)' too short", joined)
        if short_sections:
            fixes.append(
                f"Expand these sections to at least 3 substantive paragraphs: {', '.join(short_sections)}."
            )
    if "limitations" in joined:
        fixes.append(
            "Add a limitations section (minimum 3 sentences) discussing: "
            "(1) what the method cannot do, (2) when it might fail, (3) future work."
        )
    if "contribution statement not reflected" in joined:
        contrib = state.get("contribution_statement") or ""
        fixes.append(
            f"Ensure the abstract reflects the contribution: '{contrib[:100]}'. "
            "Use similar keywords and phrasing."
        )

    # Style issues
    if "ai writing patterns" in joined:
        fixes.append(
            "Remove AI-sounding phrases: replace 'delve into' with 'examine', "
            "'leverage' with 'use', delete 'it is important to note', "
            "'in recent years' (cite a specific year instead). Max 2 AI phrases allowed."
        )

    # Statistical rigor
    if "statistics" in joined or "mean±" in joined.replace("±", "±"):
        fixes.append(
            "Add statistical reporting: use 'mean ± SD (n=X)' format for all numbers, "
            "include p-values or confidence intervals for main comparisons."
        )
    if "formal problem definition" in joined or "formalization" in joined:
        fixes.append(
            "Add a 'Problem Formulation' paragraph at the start of the Method section. "
            "Define notation, input/output formally (e.g., 'Given X, find Y that minimizes ...')."
        )

    # Skeptic items
    if "skeptic_items_closed" in joined:
        skeptic = state.get("skeptic_output") or {}
        risks = (skeptic.get("rejection_risks") or [])[:3]
        if risks:
            fixes.append(
                f"Address these Skeptic concerns in method/experiments/limitations: "
                + "; ".join(str(r)[:80] for r in risks)
            )

    # Fallback: if no specific fix was generated, pass raw reasons
    if not fixes:
        fixes = gate_reasons[:5]

    return fixes[:6]
