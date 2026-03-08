"""Scout: systematic literature triage + hypothesis selection. Prompt from skills/scout/SKILL.md."""
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from researchbot.tools.search import search as web_search

def _load_prompt() -> str:
    from researchbot.tools.skills_loader import get_skill_prompt
    return get_skill_prompt("scout")


def _build_keyword_variants(topic: str) -> list:
    """Extract core concepts and build search variant queries."""
    # Split topic into key phrases for targeted searches
    words = [w for w in re.findall(r'\b\w{4,}\b', topic) if w.lower() not in {
        "this", "that", "with", "from", "have", "been", "will", "should",
        "could", "would", "more", "than", "also", "each", "such", "very",
        "using", "based", "about", "into", "only", "their", "other",
    }]
    variants = []
    # Pair-wise keyword combinations for targeted search
    if len(words) >= 4:
        variants.append(f"{words[0]} {words[1]} {words[2]}")
        variants.append(f"{words[0]} {words[-1]} {words[len(words)//2]}")
    # Method-focused variant
    variants.append(f"{topic} method algorithm")
    # Benchmark/evaluation variant
    variants.append(f"{topic} benchmark evaluation comparison")
    return variants[:4]


def run(input_data: dict) -> dict:
    """
    Input: hypotheses (list of HypothesisCards), optional topic
    Multi-source search with keyword variants + citation-aware queries,
    then LLM produces related_work, novelty/feasibility scores, selected_ids.
    Output: related_work map, novelty/feasibility scores, selected_ids, rationale
    """
    hypotheses = input_data.get("hypotheses", [])
    topic = input_data.get("topic", "")
    preferred_focus = (input_data.get("preferred_focus") or "").strip().lower()
    system = _load_prompt()

    # Build search queries: core topic + keyword variants + hypothesis claims
    search_queries = []  # (query, max_results, source)
    if topic:
        # Core topic searches
        search_queries.append((topic, 6, "arxiv"))
        search_queries.append((f"{topic} survey overview", 4, "web"))
        # Keyword variant searches for broader coverage
        for variant in _build_keyword_variants(topic):
            search_queries.append((variant, 3, "arxiv"))
    # Hypothesis-specific searches
    for h in hypotheses[:5]:
        claim = (h.get("claim") or "")[:80]
        if claim:
            search_queries.append((claim, 3, "arxiv"))

    # Parallel search execution
    web_results: list = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(web_search, q, n, src) for q, n, src in search_queries]
        for future in as_completed(futures):
            try:
                web_results.extend(future.result())
            except Exception:
                pass

    # 去重（按 url 或 title）
    seen = set()
    unique = []
    for r in web_results:
        key = (r.get("url") or "") or (r.get("title") or "")
        if key and key not in seen:
            seen.add(key)
            unique.append(r)

    # Filter out results with empty snippets (not useful for grounding)
    quality_results = [r for r in unique if (r.get("snippet") or "").strip()]
    if len(quality_results) < len(unique):
        print(f"[scout] Filtered {len(unique) - len(quality_results)} results with empty snippets.", flush=True)

    search_block = "No web search results (check network or install duckduckgo-search)."
    if quality_results:
        search_block = json.dumps(
            [{"title": r.get("title", ""), "snippet": r.get("snippet", ""), "url": r.get("url", "")} for r in quality_results],
            indent=2,
            ensure_ascii=False,
        )
    elif unique:
        # All results had empty snippets — use titles only but warn
        search_block = json.dumps(
            [{"title": r.get("title", ""), "snippet": "(no abstract available)", "url": r.get("url", "")} for r in unique],
            indent=2,
            ensure_ascii=False,
        )

    user = (
        f"Topic: {topic}\n\n"
        f"Web search results (use these to build related_work and scores):\n{search_block}\n\n"
        f"Hypotheses (JSON):\n{json.dumps(hypotheses, indent=2)}\n\n"
    )
    if preferred_focus == "system":
        user += (
            "Selection bias: The user prefers SYSTEM-oriented research. When choosing selected_ids (1–2 hypotheses), "
            "prefer hypotheses that concern system design, architecture, algorithms, or performance (latency, throughput, scalability). "
            "Favor feasibility for building or evaluating a system.\n\n"
        )
    elif preferred_focus in ("theory", "empirical", "analysis"):
        user += f"Selection bias: Prefer hypotheses that best match contribution type '{preferred_focus}' when scoring and selecting.\n\n"
    user += "Output valid JSON only."
    from researchbot.tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True)
    try:
        out = json.loads(raw)
        if not isinstance(out, dict):
            out = {}
    except json.JSONDecodeError:
        out = {}
    related_work = out.get("related_work") or []
    hypothesis_scores = out.get("hypothesis_scores") or []
    selected_ids = out.get("selected_ids") or []
    if not selected_ids and hypotheses:
        fallback_id = hypotheses[0].get("id") or "H1"
        selected_ids = [fallback_id]
    # Filter out None/empty and ensure string type
    selected_ids = [str(s) for s in selected_ids if s]
    if not selected_ids and hypotheses:
        selected_ids = ["H1"]
    return {
        "related_work": related_work,
        "hypothesis_scores": hypothesis_scores,
        "selected_ids": selected_ids,
        "selection_rationale": out.get("selection_rationale", ""),
        "web_results_count": len(unique),
    }