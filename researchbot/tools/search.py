"""Web and academic search tool. Supports DuckDuckGo (web), ArXiv, and Semantic Scholar."""
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

# Global semaphore: limit concurrent ArXiv requests to avoid HTTP 429
_arxiv_semaphore = threading.Semaphore(2)


def _sanitize_query(query: str, max_len: int = 150) -> str:
    """Strip characters that break ArXiv/SS query parsers and truncate."""
    # Remove special regex/URL chars that confuse the ArXiv API parser
    cleaned = re.sub(r"[^\w\s\-.,:/']", " ", query)
    # Collapse whitespace and truncate
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len]


# ──────────────────────────────────────────────
# DuckDuckGo (web search, no API key needed)
# ──────────────────────────────────────────────

_DDGS_IMPL = None


def _get_ddgs_impl():
    global _DDGS_IMPL
    if _DDGS_IMPL is not None:
        return _DDGS_IMPL

    def _norm(r: dict) -> Dict[str, str]:
        return {
            "title": (r.get("title") or "").strip(),
            "snippet": (r.get("body") or r.get("snippet") or "").strip()[:500],
            "url": (r.get("href") or r.get("link") or "").strip(),
        }

    # Try the new `ddgs` package first (successor to duckduckgo_search)
    try:
        from ddgs import DDGS

        def _search(query: str, max_results: int = 10) -> List[Dict[str, str]]:
            out: List[Dict[str, str]] = []
            try:
                for r in DDGS().text(query, max_results=max_results):
                    out.append(_norm(r))
            except Exception as e:
                out.append({"title": f"[Search error: {e}]", "snippet": "", "url": ""})
            return out

        _DDGS_IMPL = _search
        return _DDGS_IMPL
    except ImportError:
        pass

    # Fallback: legacy duckduckgo_search package
    try:
        from duckduckgo_search import DDGS  # type: ignore

        def _search2(query: str, max_results: int = 10) -> List[Dict[str, str]]:
            out = []
            try:
                ddgs = DDGS()
                for r in ddgs.text(query, max_results=max_results):
                    out.append(_norm(r))
            except Exception as e:
                out.append({"title": f"[Search error: {e}]", "snippet": "", "url": ""})
            return out

        _DDGS_IMPL = _search2
        return _DDGS_IMPL
    except ImportError:
        pass

    return None


def _search_web(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    impl = _get_ddgs_impl()
    if impl is not None:
        return impl(query, max_results=max_results)
    print(
        "Warning: 未安装 duckduckgo-search，无法访问网络。请执行: pip install duckduckgo-search",
        file=sys.stderr,
    )
    return [
        {
            "title": f"[Placeholder] {query[:50]}...",
            "snippet": "Install duckduckgo-search for real web search.",
            "url": "https://pypi.org/project/duckduckgo-search/",
        }
    ]


# ──────────────────────────────────────────────
# ArXiv (academic papers, no API key needed)
# ──────────────────────────────────────────────

def _search_arxiv(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    try:
        import arxiv
    except ImportError:
        print("Warning: arxiv 包未安装。请执行: pip install arxiv", file=sys.stderr)
        return []

    clean_query = _sanitize_query(query)
    # Limit concurrency and retry on 429
    with _arxiv_semaphore:
        for attempt in range(4):
            try:
                client = arxiv.Client(num_retries=1, delay_seconds=1.0)
                search = arxiv.Search(query=clean_query, max_results=max_results, sort_by=arxiv.SortCriterion.Relevance)
                results = []
                for r in client.results(search):
                    results.append({
                        "title": r.title,
                        "snippet": (r.summary or "")[:500],
                        "url": r.entry_id,
                    })
                return results
            except Exception as e:
                msg = str(e)
                if "429" in msg or "Too Many Requests" in msg:
                    wait = 2 ** attempt
                    print(f"Warning: ArXiv rate-limited (429), retrying in {wait}s …", file=sys.stderr)
                    time.sleep(wait)
                else:
                    print(f"Warning: ArXiv search error: {e}", file=sys.stderr)
                    break
    return []


# ──────────────────────────────────────────────
# Semantic Scholar (academic, free REST API)
# ──────────────────────────────────────────────

def _search_semantic_scholar(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    import os
    clean_query = _sanitize_query(query)
    encoded = urllib.parse.quote(clean_query)
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={encoded}&limit={max_results}&fields=title,abstract,year,externalIds"
    )
    headers = {"User-Agent": "EfficientResearch/1.0"}
    ss_key = os.environ.get("SS_API_KEY") or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if ss_key:
        headers["x-api-key"] = ss_key
    req = urllib.request.Request(url, headers=headers)
    # Retry with exponential backoff on 429 (rate-limit) responses
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            results = []
            for p in data.get("data") or []:
                paper_id = p.get("paperId", "")
                external = p.get("externalIds") or {}
                arxiv_id = external.get("ArXiv")
                url_str = (
                    f"https://arxiv.org/abs/{arxiv_id}"
                    if arxiv_id
                    else f"https://www.semanticscholar.org/paper/{paper_id}"
                )
                results.append({
                    "title": p.get("title") or "",
                    "snippet": (p.get("abstract") or "")[:500],
                    "url": url_str,
                })
            return results
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt  # 1, 2, 4, 8 seconds
                print(f"Warning: Semantic Scholar rate-limited (429), retrying in {wait}s …", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"Warning: Semantic Scholar search error: {e}", file=sys.stderr)
                break
        except Exception as e:
            print(f"Warning: Semantic Scholar search error: {e}", file=sys.stderr)
            break
    return []


# ──────────────────────────────────────────────
# Deduplication
# ──────────────────────────────────────────────

def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation/whitespace for fuzzy title matching."""
    return re.sub(r"[^\w\s]", "", title.lower()).strip()


def _deduplicate(results: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Deduplicate by URL and fuzzy title match."""
    seen_urls: set = set()
    seen_titles: set = set()
    out: List[Dict[str, str]] = []
    for r in results:
        url = (r.get("url") or "").strip()
        title = r.get("title") or ""
        norm_title = _normalize_title(title)
        # Skip if we've seen the same URL or a very similar title
        if url and url in seen_urls:
            continue
        if norm_title and len(norm_title) > 10 and norm_title in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if norm_title:
            seen_titles.add(norm_title)
        out.append(r)
    return out


# ──────────────────────────────────────────────
# Unified search interface
# ──────────────────────────────────────────────

def search(
    query: str,
    max_results: int = 10,
    source: str = "auto",
    **kwargs: Any,
) -> List[Dict[str, str]]:
    """
    Unified search interface.

    source="auto"   — tries ArXiv first, falls back to DuckDuckGo (good for academic queries)
    source="arxiv"  — ArXiv only (academic papers)
    source="ss"     — Semantic Scholar only (academic papers with citations)
    source="web"    — DuckDuckGo only (blogs, surveys, web pages)
    source="all"    — combines ArXiv + Semantic Scholar + DuckDuckGo, deduped
    """
    if source == "arxiv":
        return _search_arxiv(query, max_results=max_results)

    if source == "ss":
        return _search_semantic_scholar(query, max_results=max_results)

    if source == "web":
        return _search_web(query, max_results=max_results)

    if source == "all":
        per = max(2, max_results // 3)
        # Run all three sources in parallel
        from concurrent.futures import ThreadPoolExecutor, as_completed
        combined: List[Dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(_search_arxiv, query, per),
                executor.submit(_search_semantic_scholar, query, per),
                executor.submit(_search_web, query, per),
            ]
            for f in as_completed(futures):
                try:
                    combined.extend(f.result())
                except Exception:
                    pass
        return _deduplicate(combined)[:max_results]

    # source="auto": academic-first, fallback to web
    academic = _search_arxiv(query, max_results=max_results)
    if academic:
        return academic[:max_results]
    return _search_web(query, max_results=max_results)
