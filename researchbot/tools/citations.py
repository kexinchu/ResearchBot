"""Citation helpers: BibTeX generation from annotated_bib metadata."""
import re
from typing import Any, Dict, List
from pathlib import Path


def _sanitize_bib_field(value: str) -> str:
    """Escape special LaTeX characters in a BibTeX field value."""
    return str(value).replace("{", "\\{").replace("}", "\\}").replace("\\\\", "\\")


def bib_entry_from_annotated(entry: Dict[str, Any]) -> str:
    """Build a BibTeX entry string from an annotated_bib dict.

    Annotated bib fields (from DeepResearcher):
        key, title, contribution, settings, reproduce_notes,
        year (optional), authors (optional), url (optional), arxiv_id (optional)
    """
    key = re.sub(r'\W+', '_', str(entry.get("key") or "ref")).strip("_") or "ref"
    title = entry.get("title") or "Untitled"
    year = entry.get("year") or "2024"
    authors = entry.get("authors") or "Anonymous"
    url = entry.get("url") or entry.get("arxiv_url") or ""

    # Choose entry type: @article if url looks like arxiv, else @misc
    if "arxiv.org" in url:
        entry_type = "article"
        extra = f"  journal = {{arXiv preprint}},\n  year = {{{year}}},\n"
        if url:
            extra += f"  url = {{{url}}},\n"
    elif url:
        entry_type = "misc"
        extra = f"  howpublished = {{\\url{{{url}}}}},\n  year = {{{year}}},\n"
    else:
        entry_type = "misc"
        extra = f"  year = {{{year}}},\n"

    bib = (
        f"@{entry_type}{{{key},\n"
        f"  title = {{{{{_sanitize_bib_field(title)}}}}},\n"
        f"  author = {{{{{_sanitize_bib_field(authors)}}}}},\n"
        f"{extra}"
        f"}}"
    )
    return bib


def save_citations_to_bib(citations: List[Dict[str, Any]], path: str | Path) -> None:
    """Write references.bib from a list of citation dicts.

    Each dict should have at minimum 'key' and 'title'.
    If 'bib_entry' is present, it is used as-is; otherwise bib_entry_from_annotated() is called.
    Ensures all BibTeX keys are unique by appending suffix on collision.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    seen_keys: set = set()
    lines = []
    for i, c in enumerate(citations):
        # Ensure unique key before generating entry
        raw_key = re.sub(r'\W+', '_', str(c.get("key") or "ref")).strip("_") or f"ref_{i}"
        key = raw_key
        if key in seen_keys:
            key = f"{key}_{i}"
        seen_keys.add(key)
        if key != (c.get("key") or ""):
            c = dict(c)  # don't mutate original
            c["key"] = key
        entry = c.get("bib_entry") or bib_entry_from_annotated(c)
        lines.append(entry)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
