"""LaTeX builder: ACM sigconf double-column template with claim-tag normalization and table generation."""
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _normalize_for_latex(text: str) -> str:
    """Convert pipeline audit tags into LaTeX-safe forms.

    - [CITE:key]       → \\cite{key}    (required for BibTeX to compile)
    - [EVID:exp_N]     → \\textsuperscript{[exp\\_N]}  (keeps traceability, compiles)
    - [SPEC]           → \\textsuperscript{[spec]}       (marks speculation)
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
    Returns a string of LaTeX code containing one \\begin{table} per entry.
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
    """Append LaTeX table environments to the results section.

    Returns a new sections dict with tables injected into 'results'.
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
    """Write main.tex (ACM sigconf double-column) to output_dir.

    Converts [CITE:key] → \\cite{key} and other audit tags before writing.
    Inserts \\title / \\author / \\maketitle so the document compiles.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    bib_keys = bib_keys or []

    safe_title = paper_title.replace("&", r"\&").replace("_", r"\_") if paper_title else "Research Paper"

    # ACM sigconf: double-column, nonacm removes rights-management boilerplate
    # \PassOptionsToPackage{disable}{microtype} must precede \documentclass to prevent
    # the "font expansion only possible with scalable fonts" pdfTeX error on systems
    # with bitmap Type 3 fonts.
    # NOTE: \maketitle is emitted AFTER \begin{abstract}...\end{abstract} per ACM requirements
    preamble = (
        r"\PassOptionsToPackage{disable}{microtype}" + "\n"
        r"\documentclass[sigconf,nonacm]{acmart}" + "\n"
        r"\usepackage[T1]{fontenc}" + "\n"
        r"\usepackage{amsmath,amssymb,amsfonts}" + "\n"
        r"\usepackage{graphicx}" + "\n"
        r"\usepackage{textcomp}" + "\n"
        r"\usepackage{xcolor}" + "\n"
        r"\usepackage{booktabs}" + "\n"
        r"\begin{document}" + "\n"
        f"\\title{{{safe_title}}}\n"
        f"\\author{{{paper_authors}}}\n"
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

    # ACM requires abstract BEFORE \maketitle
    abstract_raw = sections.get("abstract", "")
    abstract_content = _normalize_for_latex(abstract_raw.strip()) if abstract_raw.strip() else "% TODO: Abstract"
    parts = [
        preamble,
        "\\begin{abstract}\n" + abstract_content + "\n\\end{abstract}\n",
        r"\maketitle" + "\n\n",
    ]

    body_order = [n for n in order if n != "abstract"]
    for name in body_order:
        raw = sections.get(name, "")
        content = _normalize_for_latex(raw.strip()) if raw.strip() else "% TODO: " + section_titles[name]
        title = section_titles.get(name, name.replace("_", " ").title())
        parts.append("\\section{" + title + "}\n\n" + content + "\n\n")

    parts.append("\n")
    if bib_keys:
        # ACM uses ACM-Reference-Format bibstyle (bundled with acmart)
        parts.append("\\bibliographystyle{ACM-Reference-Format}\n\\bibliography{references}\n")
    parts.append("\\end{document}\n")

    main_tex = output_dir / f"{main_name}.tex"
    main_tex.write_text("".join(parts), encoding="utf-8")
    return main_tex


def compile_pdf(
    output_dir: str | Path,
    main_name: str = "main",
) -> Optional[Path]:
    """Compile main.tex → main.pdf using pdflatex + bibtex.

    Runs the standard 4-pass sequence: pdflatex → bibtex → pdflatex → pdflatex.
    Returns the Path to the PDF on success, None if compilation fails or pdflatex is unavailable.
    """
    import shutil
    output_dir = Path(output_dir)
    tex_file = output_dir / f"{main_name}.tex"
    pdf_file = output_dir / f"{main_name}.pdf"

    if not tex_file.exists():
        print(f"[latex] compile_pdf: {tex_file} not found", flush=True)
        return None

    if not shutil.which("pdflatex"):
        print("[latex] pdflatex not found — skipping PDF compilation", flush=True)
        return None

    def _run(cmd: list) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, cwd=str(output_dir),
            capture_output=True, text=True, timeout=120,
        )

    try:
        # Pass 1 — generate aux
        _run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"{main_name}.tex"])
        # BibTeX — resolve citations
        bib_file = output_dir / "references.bib"
        if bib_file.exists():
            _run(["bibtex", main_name])
        # Pass 2 + 3 — resolve cross-references
        _run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"{main_name}.tex"])
        r = _run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"{main_name}.tex"])

        if pdf_file.exists():
            return pdf_file
        # Log first error line for diagnosis
        for line in (r.stdout + r.stderr).splitlines():
            if line.startswith("!"):
                print(f"[latex] compile error: {line}", flush=True)
                break
    except Exception as e:
        print(f"[latex] compile_pdf exception: {e}", flush=True)

    return None
