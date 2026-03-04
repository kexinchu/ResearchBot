"""Reviewer: venue-specific paper review with 0-5 scoring.
Skills loaded from skills/reviewer/<venue>.md.
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILL_DIR = _REPO_ROOT / "skills" / "reviewer"

# venue_key -> (display_name, skill_file)
VENUES: Dict[str, tuple] = {
    "mlsys":   ("MLSys",   _SKILL_DIR / "mlsys.md"),
    "vldb":    ("VLDB",    _SKILL_DIR / "vldb.md"),
    "neurips": ("NeurIPS", _SKILL_DIR / "neurips.md"),
    "aaai":    ("AAAI",    _SKILL_DIR / "aaai.md"),
}

PASS_SCORE = 4  # overall score threshold for acceptance


def _load_skill(venue_key: str) -> str:
    _, skill_path = VENUES[venue_key]
    try:
        return skill_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"You are a rigorous academic reviewer for {VENUES[venue_key][0]}. Score 0-5 and output JSON."


def _paper_text(state: dict) -> str:
    """Flatten paper sections into readable text for reviewers."""
    sections = (
        (state.get("editor_output") or state.get("writer_output") or {})
        .get("sections") or {}
    )
    order = ["abstract", "intro", "background", "method", "experiments",
             "results", "related_work", "limitations", "conclusion"]
    parts = []
    for key in order:
        content = sections.get(key, "").strip()
        if content:
            parts.append(f"\\section{{{key.replace('_', ' ').title()}}}\n{content}")
    return "\n\n".join(parts) or "No paper content available."


def run_single(venue_key: str, state: dict) -> dict:
    """Run one reviewer for a given venue. Returns the review dict."""
    venue_name, _ = VENUES[venue_key]
    system = _load_skill(venue_key)
    topic = state.get("topic", "")
    paper_text = _paper_text(state)
    exp_output = state.get("experimenter_output") or {}

    user = (
        f"Topic: {topic}\n\n"
        f"Paper content:\n{paper_text}\n\n"
        f"Experiment plan & results:\n{json.dumps(exp_output, indent=2, ensure_ascii=False)}\n\n"
        f"Please review this paper as a {venue_name} reviewer. "
        f"Output a single JSON review object matching the format in your instructions."
    )
    from tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True, max_tokens=2048)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}

    # Normalize: ensure required fields exist
    scores = out.get("scores") or {}
    overall = scores.get("overall", 0)
    try:
        overall_int = int(float(str(overall)))
    except (ValueError, TypeError):
        overall_int = 0
    return {
        "venue": out.get("venue") or venue_name,
        "scores": scores,
        "overall": overall_int,
        "strengths": out.get("strengths") or [],
        "weaknesses": out.get("weaknesses") or [],
        "required_revisions": out.get("required_revisions") or [],
        "recommendation": out.get("recommendation") or "borderline",
    }


def run_all(state: dict, venues: List[str] = None) -> List[dict]:
    """Run all configured venue reviewers in parallel and return list of review dicts."""
    if venues is None:
        venues = list(VENUES.keys())
    reviews = [None] * len(venues)
    with ThreadPoolExecutor(max_workers=len(venues)) as executor:
        futures = {executor.submit(run_single, vk, state): i for i, vk in enumerate(venues)}
        for future in as_completed(futures):
            idx = futures[future]
            reviews[idx] = future.result()
    return reviews


def all_pass(reviews: List[dict], threshold: int = PASS_SCORE) -> bool:
    return bool(reviews) and all(r.get("overall", 0) >= threshold for r in reviews)


def collect_revisions(reviews: List[dict]) -> List[str]:
    """Merge required_revisions from all reviewers, deduped."""
    seen = set()
    out = []
    for r in reviews:
        for rev in r.get("required_revisions") or []:
            key = rev[:60].lower()
            if key not in seen:
                seen.add(key)
                out.append(f"[{r['venue']}] {rev}")
    return out
