"""Write structured notes to Obsidian vault as markdown with YAML frontmatter."""
from pathlib import Path
from typing import Optional

from researchbot.config import get_obsidian_vault_path
from researchbot.models import PaperNote, IdeaNote
from researchbot.tools.io import write_markdown


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    # Remove or replace characters invalid in filenames
    invalid = '<>:"/\\|?*'
    for ch in invalid:
        name = name.replace(ch, "")
    # Collapse whitespace
    name = " ".join(name.split())
    # Truncate
    return name[:120].strip()


def _extract_short_name(title: str) -> str:
    """Extract a short system/method name from the paper title.

    Heuristics:
      - "OOD-DiskANN: Efficient and ..." → "OOD-DiskANN"
      - "vLLM — Efficient Memory ..."    → "vLLM"
      - "Efficient KV Cache ..."          → first 4 words
    """
    # Try splitting by common delimiters: colon, em-dash, en-dash, pipe
    for sep in [":", "：", "—", "–", "|"]:
        if sep in title:
            candidate = title.split(sep)[0].strip()
            if 2 <= len(candidate) <= 60:
                return candidate
    # No delimiter found: take first 4 words
    words = title.split()[:4]
    return " ".join(words)


def _make_paper_filename(note) -> str:
    """Generate filename as SystemName_FirstAuthor_Year.

    Example: OOD-DiskANN_Shikhar-Jaiswal_2022
    Falls back to short name extracted from title if system_name is not available.
    """
    parts = []

    # System name
    sys_name = (note.system_name or "").strip()
    if sys_name:
        parts.append(_sanitize_filename(sys_name))
    else:
        # Fallback: extract short name from title (before colon/dash)
        short = _extract_short_name(note.title)
        parts.append(_sanitize_filename(short))

    # First author (last name or full name with hyphens)
    if note.authors:
        first_author = note.authors[0].strip()
        # Replace spaces with hyphens for readability
        first_author = first_author.replace(" ", "-")
        parts.append(_sanitize_filename(first_author))

    # Year
    if note.year:
        parts.append(str(note.year))

    return "_".join(parts) if parts else _sanitize_filename(note.title)


def _format_yaml_list(items: list) -> str:
    """Format a list for YAML frontmatter."""
    if not items:
        return "[]"
    lines = "\n".join(f"  - {item}" for item in items)
    return f"\n{lines}"


def _format_section(content) -> str:
    """Format a note section, handling both strings and lists."""
    if isinstance(content, list):
        return "\n".join(f"- {item}" for item in content)
    return str(content) if content else ""


def write_paper_note(
    note: PaperNote,
    vault_path: Optional[str] = None,
) -> Path:
    """Write a paper note to Obsidian vault under Papers-<paper_type>/.

    Returns the path to the written file.
    """
    vault = Path(vault_path or get_obsidian_vault_path())
    paper_dir = vault / f"Papers-{note.paper_type}"
    paper_dir.mkdir(parents=True, exist_ok=True)
    filename = _make_paper_filename(note) + ".md"
    filepath = paper_dir / filename

    authors_yaml = _format_yaml_list(note.authors)
    tags_yaml = _format_yaml_list(note.tags)

    md = f"""---
title: "{note.title}"
type: paper
paper_type: {note.paper_type}
authors: {authors_yaml}
year: {note.year or ""}
venue: "{note.venue}"
source_url: "{note.source_url}"
zotero_key: "{note.zotero_key}"
tags: {tags_yaml}
created_at: {note.created_at}
updated_at: {note.updated_at}
status: {note.status}
---

# {note.title}

## Problem
{_format_section(note.problem)}

## Importance
{_format_section(note.importance)}

## Method

### Motivation
{_format_section(note.motivation)}

### Challenge
{_format_section(note.challenge)}

### Design
{_format_section(note.design)}

## Related Work & Positioning
{_format_section(note.related_work)}

## Key Results
{_format_section(note.key_results)}

## Summary
{_format_section(note.summary)}

## Limitations
{_format_section(note.limitations)}

## Insights for My Research
{_format_section(note.insights)}

## Personal Notes
{_format_section(note.personal_notes)}
"""

    write_markdown(filepath, md)
    return filepath


def write_idea_note(
    note: IdeaNote,
    vault_path: Optional[str] = None,
) -> Path:
    """Write an idea note to Obsidian vault under Idea/.

    Returns the path to the written file.
    """
    vault = Path(vault_path or get_obsidian_vault_path())
    idea_dir = vault / "Idea"
    idea_dir.mkdir(parents=True, exist_ok=True)
    filename = _sanitize_filename(note.title) + ".md"
    filepath = idea_dir / filename

    tags_yaml = _format_yaml_list(note.tags)

    md = f"""---
title: "{note.title}"
type: idea
tags: {tags_yaml}
created_at: {note.created_at}
updated_at: {note.updated_at}
status: {note.status}
---

# {note.title}

## Hypothesis
{_format_section(note.hypothesis)}

## Motivation
{_format_section(note.motivation)}

## Related Directions
{_format_section(note.related_directions)}

## Open Questions
{_format_section(note.open_questions)}

## Next Steps
{_format_section(note.next_steps)}

## Personal Notes
{_format_section(note.personal_notes)}
"""

    write_markdown(filepath, md)
    return filepath
