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


_TEMPLATES = {
    "acm": {
        "preamble_pre": r"\PassOptionsToPackage{disable}{microtype}" + "\n",
        "documentclass": r"\documentclass[sigconf,nonacm]{acmart}",
        "packages": [
            r"\usepackage[T1]{fontenc}",
            r"\usepackage{amsmath,amssymb,amsfonts}",
            r"\usepackage{graphicx}",
            r"\usepackage{textcomp}",
            r"\usepackage{xcolor}",
            r"\usepackage{booktabs}",
        ],
        "abstract_before_maketitle": True,
        "bibstyle": "ACM-Reference-Format",
    },
    "neurips": {
        "preamble_pre": "",
        "documentclass": r"\documentclass{article}",
        "packages": [
            r"\usepackage[final]{neurips_2024}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage{amsmath,amssymb,amsfonts}",
            r"\usepackage{graphicx}",
            r"\usepackage{booktabs}",
            r"\usepackage{hyperref}",
            r"\usepackage{xcolor}",
        ],
        "abstract_before_maketitle": False,
        "bibstyle": "plainnat",
    },
    "icml": {
        "preamble_pre": "",
        "documentclass": r"\documentclass[accepted]{icml2024}",
        "packages": [
            r"\usepackage[T1]{fontenc}",
            r"\usepackage{amsmath,amssymb,amsfonts}",
            r"\usepackage{graphicx}",
            r"\usepackage{booktabs}",
            r"\usepackage{hyperref}",
            r"\usepackage{xcolor}",
        ],
        "abstract_before_maketitle": False,
        "bibstyle": "icml2024",
    },
    "iclr": {
        "preamble_pre": "",
        "documentclass": r"\documentclass{article}",
        "packages": [
            r"\usepackage{iclr2025_conference}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage{amsmath,amssymb,amsfonts}",
            r"\usepackage{graphicx}",
            r"\usepackage{booktabs}",
            r"\usepackage{hyperref}",
            r"\usepackage{xcolor}",
        ],
        "abstract_before_maketitle": False,
        "bibstyle": "iclr2025_conference",
    },
}


def _detect_template(venue: str) -> str:
    """Detect LaTeX template from venue string."""
    v = venue.lower()
    if "neurips" in v or "nips" in v:
        return "neurips"
    if "icml" in v:
        return "icml"
    if "iclr" in v:
        return "iclr"
    return "acm"


def build_latex(
    sections: Dict[str, str],
    output_dir: str | Path,
    main_name: str = "main",
    bib_keys: Optional[List[str]] = None,
    paper_title: str = "",
    paper_authors: str = "Anonymous Authors",
    venue: str = "",
) -> Path:
    """Write main.tex to output_dir using venue-appropriate template.

    Supported templates: ACM sigconf (default), NeurIPS, ICML, ICLR.
    Converts [CITE:key] → \\cite{key} and other audit tags before writing.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    bib_keys = bib_keys or []

    safe_title = paper_title.replace("&", r"\&").replace("_", r"\_") if paper_title else "Research Paper"

    # Select template based on venue
    template_name = _detect_template(venue)
    tmpl = _TEMPLATES[template_name]

    # Build preamble
    preamble_lines = []
    if tmpl["preamble_pre"]:
        preamble_lines.append(tmpl["preamble_pre"])
    preamble_lines.append(tmpl["documentclass"])
    preamble_lines.extend(tmpl["packages"])
    preamble_lines.append(r"\begin{document}")
    preamble_lines.append(f"\\title{{{safe_title}}}")
    preamble_lines.append(f"\\author{{{paper_authors}}}")
    preamble = "\n".join(preamble_lines) + "\n"

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

    abstract_raw = sections.get("abstract", "")
    abstract_content = _normalize_for_latex(abstract_raw.strip()) if abstract_raw.strip() else "% TODO: Abstract"

    parts = [preamble]
    if tmpl["abstract_before_maketitle"]:
        # ACM style: abstract before \maketitle
        parts.append("\\begin{abstract}\n" + abstract_content + "\n\\end{abstract}\n")
        parts.append(r"\maketitle" + "\n\n")
    else:
        # NeurIPS/ICML/ICLR style: \maketitle before abstract
        parts.append(r"\maketitle" + "\n\n")
        parts.append("\\begin{abstract}\n" + abstract_content + "\n\\end{abstract}\n\n")

    body_order = [n for n in order if n != "abstract"]
    for name in body_order:
        raw = sections.get(name, "")
        content = _normalize_for_latex(raw.strip()) if raw.strip() else "% TODO: " + section_titles[name]
        title = section_titles.get(name, name.replace("_", " ").title())
        parts.append("\\section{" + title + "}\n\n" + content + "\n\n")

    parts.append("\n")
    if bib_keys:
        parts.append(f"\\bibliographystyle{{{tmpl['bibstyle']}}}\n\\bibliography{{references}}\n")
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
