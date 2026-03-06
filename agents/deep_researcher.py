"""DeepResearcher: annotated bib with metadata, related_work_draft, baselines, gap summary."""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from tools.search import search as web_search


def _parallel_search(queries: List[Tuple[str, int, str]], max_workers: int = 4) -> list:
    """Run multiple (query, max_results, source) searches in parallel and return deduplicated results."""
    all_results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(web_search, q, n, source) for q, n, source in queries]
        for future in as_completed(futures):
            try:
                all_results.extend(future.result())
            except Exception:
                pass
    # Deduplicate by URL or title
    seen: set = set()
    unique: list = []
    for r in all_results:
        key = r.get("url") or r.get("title") or ""
        if key and key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _load_prompt() -> str:
    from tools.skills_loader import get_skill_prompt
    return get_skill_prompt("deep_researcher")


def run(input_data: dict) -> dict:
    """
    Input: selected hypotheses, scout_output, contribution_statement, extra_queries
    Output: annotated_bib, related_work_draft, baseline_checklist, metrics_checklist, gap_summary
    """
    hypotheses = input_data.get("hypotheses", [])
    scout = input_data.get("scout_output") or {}
    related_work = scout.get("related_work", [])
    contribution_statement = input_data.get("contribution_statement") or ""
    extra_queries: list = input_data.get("extra_queries") or []

    # Build parallel search batch: (query, max_results, source)
    queries: List[Tuple[str, int, str]] = []
    for h in hypotheses:
        claim = (h.get("claim") or "")[:100]
        if claim:
            queries.append((claim, 5, "arxiv"))
            queries.append((claim, 3, "ss"))
    if related_work:
        topic_ctx = " ".join(r.get("paper", "") for r in related_work[:3])[:100]
        if topic_ctx:
            queries.append((topic_ctx, 5, "arxiv"))
    # Targeted re-search pass (Skeptic rejection_risks or gate failures)
    for q in extra_queries[:6]:
        q_short = str(q)[:100]
        if q_short:
            queries.append((q_short, 4, "arxiv"))
            queries.append((q_short, 3, "ss"))

    unique = _parallel_search(queries, max_workers=3)

    search_block = json.dumps(
        [{"title": r.get("title", ""), "snippet": r.get("snippet", ""), "url": r.get("url", "")} for r in unique],
        indent=2, ensure_ascii=False,
    ) if unique else "No additional web results."

    system = _load_prompt()
    extra_block = ""
    if extra_queries:
        extra_block = (
            "\nIMPORTANT – targeted re-search pass. The reviewer (Skeptic) raised:\n"
            + json.dumps(extra_queries, indent=2)
            + "\nPrioritise finding evidence that directly addresses these concerns.\n"
        )

    user = (
        f"Contribution statement: {contribution_statement}\n\n"
        f"Selected hypotheses:\n{json.dumps(hypotheses, indent=2)}\n\n"
        f"Related work (from Scout):\n{json.dumps(related_work, indent=2)}\n\n"
        f"Web search results:\n{search_block}\n"
        f"{extra_block}\n"
        "Output valid JSON only."
    )

    from tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True, max_tokens=4096)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}

    return {
        "annotated_bib":      out.get("annotated_bib") or [],
        "related_work_draft": out.get("related_work_draft") or "",
        "baseline_checklist": out.get("baseline_checklist") or [],
        "metrics_checklist":  out.get("metrics_checklist") or [],
        "gap_summary":        out.get("gap_summary", ""),
    }