"""LaTeX builder: IEEEtran template with claim-tag normalization and table generation."""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _normalize_for_latex(text: str) -> str:
    """Convert pipeline audit tags into LaTeX-safe forms.

    - [CITE:key]       → \\cite{key}    (required for BibTeX to compile)
    - [EVID:exp_N]     → \\textsuperscript{[exp\\_N]}  (keeps traceability, compiles)
    - [SPEC]           → \\textsuperscript{[?]}          (marks speculation)
    """
    # [CITE:key] → \cite{key}
    text = re.sub(r'\[CITE:([^\]]+)\]', r'\\cite{\1}', text)
    # [EVID:...] → superscript label
    text = re.sub(r'\[EVID:([^\]]+)\]', lambda m: r'\textsuperscript{[' + m.group(1).replace('_', r'\_') + ']}', text)
    # [SPEC] → superscript marker
    text = text.replace('[SPEC]', r'\textsuperscript{[\textit{spec}]}')
    return text


def _escape_cell(value: str) -> str:
    """Escape LaTeX special chars in a table cell value."""
    return str(value).replace("&", r"\&").replace("%", r"\%").replace("_", r"\_").replace("#", r"\#")


def result_tables_to_latex(result_tables: List[Dict[str, Any]]) -> str:
    """Convert Experimenter's result_tables JSON to LaTeX table environments.

    Each table in result_tables has: id, caption, columns, rows, note.
    Returns a string of LaTeX code containing one \begin{table} per entry.
    """
    blocks = []
    for t in result_tables:
        tid = t.get("id", "tab")
        caption = _escape_cell(t.get("caption") or "Results")
        columns = t.get("columns") or []
        rows = t.get("rows") or []
        note = t.get("note") or ""

        if not columns or not rows:
            continue

        col_spec = "l" + "c" * (len(columns) - 1)
        header_cells = " & ".join(f"\\textbf{{{_escape_cell(c)}}}" for c in columns)

        row_lines = []
        for row in rows:
            cells = " & ".join(_escape_cell(str(v)) for v in row)
            row_lines.append(f"    {cells} \\\\")

        note_line = f"\n    \\footnotesize{{\\textit{{{_escape_cell(note)}}}}}" if note else ""

        block = (
            "\\begin{table}[htbp]\n"
            "\\centering\n"
            f"\\caption{{{caption}}}\n"
            f"\\label{{tab:{tid}}}\n"
            f"\\begin{{tabular}}{{{col_spec}}}\n"
            "\\hline\n"
            f"    {header_cells} \\\\\n"
            "\\hline\n"
            + "\n".join(row_lines) + "\n"
            "\\hline\n"
            f"\\end{{tabular}}{note_line}\n"
            "\\end{table}"
        )
        blocks.append(block)

    return "\n\n".join(blocks)


def inject_result_tables(sections: Dict[str, str], result_tables: List[Dict[str, Any]]) -> Dict[str, str]:
    """Append LaTeX table environments to the results section (before conclusion).

    Returns a new sections dict with tables injected into 'results'.
    Separates main comparison tables (exp_*) and ablation tables (ablation_*).
    """
    if not result_tables:
        return sections

    sections = dict(sections)  # shallow copy — do not mutate caller's dict
    tables_latex = result_tables_to_latex(result_tables)
    if not tables_latex:
        return sections

    existing = sections.get("results") or ""
    sections["results"] = existing.rstrip() + "\n\n" + tables_latex
    return sections


def build_latex(
    sections: Dict[str, str],
    output_dir: str | Path,
    main_name: str = "main",
    bib_keys: Optional[List[str]] = None,
    paper_title: str = "",
    paper_authors: str = "Anonymous Authors",
) -> Path:
    """Write main.tex to output_dir.

    Converts [CITE:key] → \\cite{key} and other audit tags before writing.
    Inserts \\title / \\author / \\maketitle so the document compiles.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    bib_keys = bib_keys or []

    safe_title = paper_title.replace("&", r"\&").replace("_", r"\_") if paper_title else "Research Paper"

    preamble = (
        r"\documentclass[conference]{IEEEtran}" + "\n"
        r"\usepackage{cite}" + "\n"
        r"\usepackage{amsmath,amssymb,amsfonts}" + "\n"
        r"\usepackage{algorithmic}" + "\n"
        r"\usepackage{graphicx}" + "\n"
        r"\usepackage{textcomp}" + "\n"
        r"\usepackage{xcolor}" + "\n"
        r"\usepackage{url}" + "\n"
        r"\usepackage{hyperref}" + "\n"
        r"\begin{document}" + "\n"
        f"\\title{{{safe_title}}}\n"
        f"\\author{{{paper_authors}}}\n"
        r"\maketitle" + "\n"
    )

    order = [
        "abstract", "intro", "background", "method",
        "experiments", "results", "related_work", "limitations", "conclusion"
    ]
    section_titles = {
        "abstract":     "Abstract",
        "intro":        "Introduction",
        "background":   "Background",
        "method":       "Method",
        "experiments":  "Experiments",
        "results":      "Results",
        "related_work": "Related Work",
        "limitations":  "Limitations",
        "conclusion":   "Conclusion",
    }

    parts = [preamble]
    for name in order:
        raw = sections.get(name, "")
        content = _normalize_for_latex(raw.strip()) if raw.strip() else "% TODO: " + section_titles[name]
        if name == "abstract":
            parts.append("\\begin{abstract}\n" + content + "\n\\end{abstract}\n\n")
        else:
            title = section_titles.get(name, name.replace("_", " ").title())
            parts.append("\\section{" + title + "}\n\n" + content + "\n\n")

    parts.append("\n")
    if bib_keys:
        parts.append("\\bibliographystyle{IEEEtran}\n\\bibliography{references}\n")
    parts.append("\\end{document}\n")

    main_tex = output_dir / f"{main_name}.tex"
    main_tex.write_text("".join(parts), encoding="utf-8")
    return main_tex
