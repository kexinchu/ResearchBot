"""Scout: 粗文献探索 + 筛选。Prompt 来自 skills/scout/SKILL.md；必须能访问网络。"""
import json

from tools.search import search as web_search

def _load_prompt() -> str:
    from tools.skills_loader import get_skill_prompt
    return get_skill_prompt("scout")

def run(input_data: dict) -> dict:
    """
    Input: hypotheses (list of HypothesisCards), optional topic
    先通过网络搜索获取与 topic/hypotheses 相关的论文与博客，再让 LLM 产出 related_work、新颖性/可行性、selected_ids。
    Output: related_work map, novelty/feasibility scores, selected_ids, rationale
    """
    hypotheses = input_data.get("hypotheses", [])
    topic = input_data.get("topic", "")
    system = _load_prompt()

    # Explorer：必须访问网络，查询论文/blog
    # 学术论文查询用 ArXiv（精准），博客/survey 用 web
    web_results: list = []
    if topic:
        web_results.extend(web_search(f"{topic}", max_results=6, source="arxiv"))
        web_results.extend(web_search(f"{topic} survey overview", max_results=4, source="web"))
    for h in hypotheses[:5]:
        claim = (h.get("claim") or "")[:80]
        if claim:
            web_results.extend(web_search(f"{claim}", max_results=3, source="arxiv"))

    # 去重（按 url 或 title）
    seen = set()
    unique = []
    for r in web_results:
        key = (r.get("url") or "") or (r.get("title") or "")
        if key and key not in seen:
            seen.add(key)
            unique.append(r)

    search_block = "No web search results (check network or install duckduckgo-search)."
    if unique:
        search_block = json.dumps(
            [{"title": r.get("title", ""), "snippet": r.get("snippet", ""), "url": r.get("url", "")} for r in unique],
            indent=2,
            ensure_ascii=False,
        )

    user = (
        f"Topic: {topic}\n\n"
        f"Web search results (use these to build related_work and scores):\n{search_block}\n\n"
        f"Hypotheses (JSON):\n{json.dumps(hypotheses, indent=2)}\n\n"
        "Output valid JSON only."
    )
    from tools.llm import call_llm
    raw = call_llm(system, user, json_mode=True)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}
    related_work = out.get("related_work") or []
    hypothesis_scores = out.get("hypothesis_scores") or []
    selected_ids = out.get("selected_ids") or []
    if not selected_ids and hypotheses:
        selected_ids = [hypotheses[0].get("id")] if hypotheses else []
    return {
        "related_work": related_work,
        "hypothesis_scores": hypothesis_scores,
        "selected_ids": [str(s) for s in selected_ids],
        "selection_rationale": out.get("selection_rationale", ""),
        "web_results_count": len(unique),
    }