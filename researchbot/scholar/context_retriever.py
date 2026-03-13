"""Retrieve relevant context from local knowledge base (RAG + Zotero + Obsidian).

Used by explore and experiment commands to ground research in the user's existing paper library.
Returns a formatted string of relevant papers/notes/ideas for injection into LLM prompts.
"""
import re
from pathlib import Path
from typing import List, Dict, Any, Optional


def retrieve_context(
    topic: str,
    max_results: int = 15,
    max_chars: int = 5000,
    include_papers: bool = True,
    include_ideas: bool = True,
) -> str:
    """Retrieve relevant context from all local sources.

    Tries three sources in order:
    1. RAG (ChromaDB) — fast semantic search across indexed notes
    2. Zotero — keyword search in paper library
    3. Obsidian — direct file scan if RAG is not available

    Returns a formatted string ready for LLM prompt injection.
    """
    chunks: List[Dict[str, Any]] = []

    # 1. RAG (primary — semantic search)
    rag_results = _retrieve_from_rag(topic, max_results=max_results)
    if rag_results:
        chunks.extend(rag_results)

    # 2. Zotero (complement — keyword search for papers not yet in Obsidian)
    zotero_results = _retrieve_from_zotero(topic, max_results=5)
    if zotero_results:
        # Deduplicate against RAG results by title
        rag_titles = {c.get("title", "").lower().strip() for c in chunks}
        for z in zotero_results:
            if z.get("title", "").lower().strip() not in rag_titles:
                chunks.append(z)

    # 3. Obsidian fallback (if RAG returned nothing)
    if not rag_results:
        obsidian_results = _retrieve_from_obsidian(
            topic, max_results=max_results,
            include_papers=include_papers, include_ideas=include_ideas,
        )
        chunks.extend(obsidian_results)

    if not chunks:
        return ""

    # Format for prompt
    return _format_context(chunks, max_chars=max_chars)


def _retrieve_from_rag(topic: str, max_results: int = 15) -> List[Dict[str, Any]]:
    """Semantic search via ChromaDB."""
    try:
        from researchbot.tools.rag import query
        results = query(topic, k=max_results)
        return [
            {
                "title": r.get("title", ""),
                "text": r.get("text", ""),
                "source": "rag",
                "note_type": r.get("note_type", ""),
                "distance": r.get("distance", 0),
            }
            for r in results
        ]
    except Exception:
        return []


def _retrieve_from_zotero(topic: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Keyword search in Zotero library."""
    try:
        from pyzotero import zotero
        from researchbot.config import get_zotero_library_id, get_zotero_api_key, get_zotero_library_type

        lib_id = get_zotero_library_id()
        api_key = get_zotero_api_key()
        if not lib_id or not api_key:
            return []

        zot = zotero.Zotero(lib_id, get_zotero_library_type(), api_key)
        items = zot.items(q=topic, limit=max_results,
                          itemType="journalArticle || conferencePaper || preprint || report")

        results = []
        for item in items:
            data = item.get("data", {})
            title = data.get("title", "")
            authors = ", ".join(
                f"{c.get('firstName', '')} {c.get('lastName', '')}".strip() or c.get("name", "")
                for c in (data.get("creators") or [])[:5]
            )
            year = (data.get("date") or "")[:4]
            abstract = (data.get("abstractNote") or "")[:500]
            tags = [t.get("tag", "") for t in (data.get("tags") or [])]

            text = f"Paper: {title}"
            if authors:
                text += f" by {authors}"
            if year:
                text += f" ({year})"
            if abstract:
                text += f"\nAbstract: {abstract}"
            if tags:
                text += f"\nTags: {', '.join(tags)}"

            results.append({
                "title": title,
                "text": text,
                "source": "zotero",
                "note_type": "paper",
            })
        return results
    except Exception:
        return []


def _retrieve_from_obsidian(
    topic: str,
    max_results: int = 15,
    include_papers: bool = True,
    include_ideas: bool = True,
) -> List[Dict[str, Any]]:
    """Direct file scan of Obsidian vault (fallback when RAG is unavailable)."""
    from researchbot.config import get_obsidian_vault_path

    vault = Path(get_obsidian_vault_path())
    if not vault.exists():
        return []

    topic_lower = topic.lower()
    topic_words = set(re.findall(r'\w+', topic_lower))
    results = []

    dirs_to_scan = []
    if include_papers:
        # Scan all Papers-<type> directories
        for d in vault.iterdir():
            if d.is_dir() and d.name.startswith("Papers-"):
                dirs_to_scan.append(d)
    if include_ideas:
        idea_dir = vault / "Idea"
        if idea_dir.exists():
            dirs_to_scan.append(idea_dir)
        explore_dir = vault / "Explore"
        if explore_dir.exists():
            dirs_to_scan.append(explore_dir)

    scored = []
    for scan_dir in dirs_to_scan:
        for md_file in scan_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")[:3000]
            except Exception:
                continue
            content_lower = content.lower()
            # Score by keyword overlap
            score = sum(1 for w in topic_words if w in content_lower and len(w) > 2)
            if score > 0:
                # Extract title from frontmatter or filename
                title = md_file.stem
                m = re.search(r'^title:\s*"?(.+?)"?\s*$', content, re.MULTILINE)
                if m:
                    title = m.group(1)
                scored.append((score, title, content[:1000], str(md_file)))

    scored.sort(key=lambda x: x[0], reverse=True)

    for score, title, content, path in scored[:max_results]:
        note_type = "paper" if "/Papers-" in path else "idea"
        results.append({
            "title": title,
            "text": f"[{note_type}] {title}\n{content[:500]}",
            "source": "obsidian",
            "note_type": note_type,
        })

    return results


def _format_context(chunks: List[Dict[str, Any]], max_chars: int = 5000) -> str:
    """Format retrieved chunks into a prompt-ready string."""
    if not chunks:
        return ""

    lines = ["## Relevant context from your paper library and notes:\n"]
    total = len(lines[0])

    for i, chunk in enumerate(chunks):
        entry = chunk.get("text", "").strip()
        if not entry:
            continue
        if total + len(entry) + 10 > max_chars:
            entry = entry[:max_chars - total - 10]
            lines.append(entry)
            break
        lines.append(entry)
        lines.append("")
        total += len(entry) + 1

    return "\n".join(lines)
