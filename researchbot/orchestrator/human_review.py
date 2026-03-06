"""Human-in-the-loop: write stage results to Markdown, wait for edits, read back into state."""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def ensure_review_dir(artifacts_root: str) -> Path:
    p = Path(artifacts_root) / "review"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ═══════════════════════════════════════════════════════════════
# Write functions — output stage results to editable Markdown
# ═══════════════════════════════════════════════════════════════

def write_ideator_report(state: Dict[str, Any], review_dir: Path) -> Path:
    out_path = review_dir / "01_ideator.md"
    lines = [
        "# Ideator Report",
        "",
        "## 1. Related Work Summary",
        "",
        (state.get("related_work_summary") or "(none)").strip(),
        "",
        "---",
        "## 2. Unsolved Problems",
        "",
    ]
    for i, u in enumerate(state.get("unsolved_problems") or [], 1):
        if isinstance(u, dict):
            lines.append(f"### Problem {i}")
            lines.append(f"- **Problem**: {u.get('problem', '')}")
            lines.append(f"- **Context**: {u.get('context', '')}")
            lines.append("")
    if not state.get("unsolved_problems"):
        lines += ["(none)", ""]
    lines.extend(["---", "## 3. Research-Worthy Directions", ""])
    for i, r in enumerate(state.get("research_worthy") or [], 1):
        if isinstance(r, dict):
            lines.append(f"### Direction {i}")
            lines.append(f"- **Problem**: {r.get('problem', '')}")
            lines.append(f"- **Rationale**: {r.get('rationale', '')}")
            lines.append("")
    if not state.get("research_worthy"):
        lines += ["(none)", ""]
    lines.extend(["---", "## 4. Proposals (Motivation + Idea + Challenges)", ""])
    for i, p in enumerate(state.get("proposals") or [], 1):
        if isinstance(p, dict):
            lines.append(f"### Proposal {i}")
            lines.append(f"- **Motivation**: {p.get('motivation', '')}")
            lines.append(f"- **Idea**: {p.get('idea', '')}")
            ch = p.get("challenges") or []
            if isinstance(ch, list):
                lines.append("- **Challenges**:")
                for c in ch:
                    lines.append(f"  - {c}")
            else:
                lines.append(f"- **Challenges**: {ch}")
            lines.append("")
    if not state.get("proposals"):
        lines += ["(none)", ""]
    lines.extend(["---", "## 5. Hypotheses", ""])
    for i, h in enumerate(state.get("hypotheses") or [], 1):
        if isinstance(h, dict):
            lines.append(f"### {h.get('id', f'H{i}')}")
            lines.append(f"- **Claim**: {h.get('claim', '')}")
            lines.append(f"- **Falsifiable Test**: {h.get('falsifiable_test', '')}")
            lines.append(f"- **Minimal Experiment**: {h.get('minimal_experiment', '')}")
            lines.append(f"- **Expected Gain**: {h.get('expected_gain', '')}")
            lines.append(f"- **Risks**: {h.get('risks', '')}")
            lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_deep_research_report(state: Dict[str, Any], review_dir: Path, round_n: int) -> Path:
    out_path = review_dir / f"03_deep_research_round{round_n}.md"
    deep = state.get("deep_research_output") or {}
    bib = deep.get("annotated_bib") or []
    rw_draft = deep.get("related_work_draft") or ""
    baseline = deep.get("baseline_checklist") or []
    metrics = deep.get("metrics_checklist") or []
    gap = deep.get("gap_summary") or ""
    lines = [
        f"# DeepResearch Round {round_n}",
        "",
        "## 1. Annotated Bibliography",
        "",
    ]
    for b in bib:
        if isinstance(b, dict):
            lines.append(f"### {b.get('key', 'unknown')}")
            lines.append(f"- **Title**: {b.get('title', '')}")
            lines.append(f"- **Year**: {b.get('year', '')}")
            lines.append(f"- **Contribution**: {b.get('contribution', '')}")
            lines.append(f"- **Settings**: {b.get('settings', '')}")
            lines.append("")
    lines.extend(["---", "## 2. Related Work Draft", "", rw_draft, ""])
    lines.extend(["---", "## 3. Baseline Checklist", ""])
    lines.extend([f"- {x}" for x in baseline])
    lines.extend(["", "---", "## 4. Metrics Checklist", ""])
    lines.extend([f"- {x}" for x in metrics])
    lines.extend(["", "---", "## 5. Gap Summary", "", gap, ""])
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_experimenter_report(state: Dict[str, Any], review_dir: Path) -> Path:
    out_path = review_dir / "05_experimenter.md"
    exp = state.get("experimenter_output") or {}
    plans = exp.get("experiment_plan") or []
    valid = exp.get("theoretical_validation") or []
    summary = exp.get("result_summary") or ""
    tables = exp.get("result_tables") or []
    lines = ["# Experimenter Report", "", "## 1. Experiment Plan", ""]
    for p in plans:
        if isinstance(p, dict):
            lines.append(f"### {p.get('name', 'Experiment')} (id: {p.get('id', '')})")
            lines.append(f"- **Dataset**: {p.get('dataset', '')}")
            lines.append(f"- **Metric**: {p.get('metric', '')}")
            lines.append(f"- **Baselines**: {p.get('baselines', [])}")
            lines.append(f"- **Expected Outcome**: {p.get('expected_outcome', '')}")
            lines.append("")
    lines.extend(["---", "## 2. Theoretical Validation", ""])
    for v in valid:
        if isinstance(v, dict):
            lines.append(f"### {v.get('angle', 'Angle')}")
            lines.append(f"- **Claim**: {v.get('claim', '')}")
            lines.append(f"- **Reasoning**: {v.get('reasoning', '')}")
            lines.append("")
    lines.extend(["---", "## 3. Result Summary", "", summary, ""])
    if tables:
        lines.extend(["---", "## 4. Result Tables", ""])
        for t in tables:
            if isinstance(t, dict):
                lines.append(f"### {t.get('caption', 'Table')}")
                lines.append(f"```")
                lines.append(t.get("latex", ""))
                lines.append(f"```")
                lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_writer_report(state: Dict[str, Any], review_dir: Path) -> Path:
    """Write full paper sections to Markdown (not truncated) for human editing."""
    out_path = review_dir / "06_writer.md"
    wo = state.get("writer_output") or {}
    sections = wo.get("sections") or {}
    lines = ["# Writer Output (Paper Sections)", ""]
    for key in ["abstract", "intro", "background", "method", "experiments",
                "results", "related_work", "limitations", "conclusion"]:
        val = sections.get(key) or ""
        if val:
            lines.append(f"## {key}")
            lines.append("")
            lines.append(val)
            lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# ═══════════════════════════════════════════════════════════════
# Read-back functions — parse edited Markdown back into state
# ═══════════════════════════════════════════════════════════════

def _extract_section_content(text: str, header: str) -> str:
    """Extract content between a ## header and the next ## or --- or end of file."""
    pattern = rf"^##\s+{re.escape(header)}\s*$"
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        return ""
    start = m.end()
    # Find next ## header or --- separator
    next_section = re.search(r"^(?:##\s|---)", text[start:], re.MULTILINE)
    if next_section:
        content = text[start:start + next_section.start()]
    else:
        content = text[start:]
    return content.strip()


def _extract_h3_blocks(text: str) -> List[str]:
    """Split text into blocks starting with ### headers."""
    parts = re.split(r"(?=^###\s)", text, flags=re.MULTILINE)
    return [p.strip() for p in parts if p.strip() and p.strip().startswith("###")]


def _parse_field(block: str, field: str) -> str:
    """Extract value after '- **Field**: value' pattern."""
    pattern = rf"-\s*\*\*{re.escape(field)}\*\*\s*[:：]\s*(.*)"
    m = re.search(pattern, block, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _parse_list_items(text: str) -> List[str]:
    """Extract items from markdown list (- item)."""
    items = re.findall(r"^-\s+(.+)$", text, re.MULTILINE)
    # Filter out bold field markers (they're key-value, not list items)
    return [i.strip() for i in items if not i.strip().startswith("**")]


def read_deep_research_md(review_dir: Path, round_n: int) -> Optional[Dict[str, Any]]:
    """Parse edited DeepResearch markdown back into deep_research_output dict."""
    md_path = review_dir / f"03_deep_research_round{round_n}.md"
    if not md_path.exists():
        return None
    text = md_path.read_text(encoding="utf-8")

    # Parse annotated bibliography
    bib_section = _extract_section_content(text, "1. Annotated Bibliography")
    bib_blocks = _extract_h3_blocks(bib_section)
    annotated_bib = []
    for block in bib_blocks:
        # Header line: ### key_name
        header_m = re.match(r"###\s+(.+)", block)
        key = header_m.group(1).strip() if header_m else ""
        annotated_bib.append({
            "key": key,
            "title": _parse_field(block, "Title"),
            "year": _parse_field(block, "Year"),
            "contribution": _parse_field(block, "Contribution"),
            "settings": _parse_field(block, "Settings"),
        })

    # Related work draft
    related_work_draft = _extract_section_content(text, "2. Related Work Draft")

    # Baseline checklist
    baseline_section = _extract_section_content(text, "3. Baseline Checklist")
    baseline_checklist = _parse_list_items(baseline_section)

    # Metrics checklist
    metrics_section = _extract_section_content(text, "4. Metrics Checklist")
    metrics_checklist = _parse_list_items(metrics_section)

    # Gap summary
    gap_summary = _extract_section_content(text, "5. Gap Summary")

    return {
        "annotated_bib": annotated_bib,
        "related_work_draft": related_work_draft,
        "baseline_checklist": baseline_checklist,
        "metrics_checklist": metrics_checklist,
        "gap_summary": gap_summary,
    }


def read_experimenter_md(review_dir: Path) -> Optional[Dict[str, Any]]:
    """Parse edited Experimenter markdown back into experimenter_output dict."""
    md_path = review_dir / "05_experimenter.md"
    if not md_path.exists():
        return None
    text = md_path.read_text(encoding="utf-8")

    # Parse experiment plan
    plan_section = _extract_section_content(text, "1. Experiment Plan")
    plan_blocks = _extract_h3_blocks(plan_section)
    experiment_plan = []
    for block in plan_blocks:
        header_m = re.match(r"###\s+(.+?)(?:\s*\(id:\s*(.+?)\))?\s*$", block, re.MULTILINE)
        name = header_m.group(1).strip() if header_m else ""
        exp_id = header_m.group(2).strip() if header_m and header_m.group(2) else ""
        baselines_raw = _parse_field(block, "Baselines")
        # Try to parse list notation
        if baselines_raw.startswith("["):
            try:
                import ast
                baselines = ast.literal_eval(baselines_raw)
            except Exception:
                baselines = [baselines_raw]
        else:
            baselines = [b.strip() for b in baselines_raw.split(",") if b.strip()]
        experiment_plan.append({
            "id": exp_id,
            "name": name,
            "dataset": _parse_field(block, "Dataset"),
            "metric": _parse_field(block, "Metric"),
            "baselines": baselines,
            "expected_outcome": _parse_field(block, "Expected Outcome"),
        })

    # Parse theoretical validation
    valid_section = _extract_section_content(text, "2. Theoretical Validation")
    valid_blocks = _extract_h3_blocks(valid_section)
    theoretical_validation = []
    for block in valid_blocks:
        header_m = re.match(r"###\s+(.+)", block)
        angle = header_m.group(1).strip() if header_m else ""
        theoretical_validation.append({
            "angle": angle,
            "claim": _parse_field(block, "Claim"),
            "reasoning": _parse_field(block, "Reasoning"),
        })

    # Result summary
    result_summary = _extract_section_content(text, "3. Result Summary")

    # Result tables (optional)
    result_tables = []
    tables_section = _extract_section_content(text, "4. Result Tables")
    if tables_section:
        table_blocks = _extract_h3_blocks(tables_section)
        for block in table_blocks:
            header_m = re.match(r"###\s+(.+)", block)
            caption = header_m.group(1).strip() if header_m else "Table"
            latex_m = re.search(r"```\s*([\s\S]*?)```", block)
            latex = latex_m.group(1).strip() if latex_m else ""
            result_tables.append({"caption": caption, "latex": latex})

    return {
        "experiment_plan": experiment_plan,
        "theoretical_validation": theoretical_validation,
        "result_summary": result_summary,
        "result_tables": result_tables,
    }


def read_writer_md(review_dir: Path) -> Optional[Dict[str, str]]:
    """Parse edited Writer markdown back into sections dict."""
    md_path = review_dir / "06_writer.md"
    if not md_path.exists():
        return None
    text = md_path.read_text(encoding="utf-8")

    sections = {}
    section_keys = ["abstract", "intro", "background", "method", "experiments",
                    "results", "related_work", "limitations", "conclusion"]
    for key in section_keys:
        content = _extract_section_content(text, key)
        if content:
            sections[key] = content
    return sections if sections else None


# ═══════════════════════════════════════════════════════════════
# Interactive prompts
# ═══════════════════════════════════════════════════════════════

def prompt_hypothesis_selection(state: Dict[str, Any]) -> List[str]:
    """Print proposals/hypotheses, wait for user to select by number."""
    hypotheses = state.get("hypotheses") or []
    proposals = state.get("proposals") or []
    if proposals:
        print("\n" + "=" * 60)
        print("  Select proposal(s) for DeepResearch (e.g. 1 or 1,3)")
        print("=" * 60)
        for i, p in enumerate(proposals, 1):
            if isinstance(p, dict):
                idea = (p.get("idea") or "")[:80]
                print(f"  {i}. {idea}")
    else:
        print("\n" + "=" * 60)
        print("  Select hypothesis(es) for DeepResearch (e.g. 1 or 1,3)")
        print("=" * 60)
        for i, h in enumerate(hypotheses, 1):
            if isinstance(h, dict):
                claim = (h.get("claim") or "")[:80]
                print(f"  {i}. [{h.get('id', f'H{i}')}] {claim}")
    try:
        raw = input("\nEnter number(s) (comma or space separated): ").strip()
    except EOFError:
        raw = "1"
    parts = raw.replace(",", " ").split()
    indices = []
    for p in parts:
        try:
            idx = int(p)
            if 1 <= idx <= max(len(proposals), len(hypotheses), 1):
                indices.append(idx)
        except ValueError:
            pass
    if not indices and (proposals or hypotheses):
        indices = [1]
    selected_ids = []
    for idx in sorted(indices):
        if idx <= len(hypotheses):
            selected_ids.append((hypotheses[idx - 1] or {}).get("id") or f"H{idx}")
    return selected_ids[:5]


def prompt_edit_and_confirm(phase: str, md_path: Path, round_n: Optional[int] = None) -> str:
    """Print path to MD file, wait for user to edit and confirm.
    Returns 'continue' (re-run this stage) or 'next' (proceed to next stage)."""
    print("\n" + "=" * 60)
    print(f"  [{phase}] Results written to:")
    print(f"  {md_path}")
    print("")
    print("  You can now edit the Markdown file above.")
    print("  After editing, your changes will be read back as input.")
    print("")
    if phase == "DeepResearch":
        print("  y = run another round of DeepResearch")
        print("  n = proceed to next stage (Skeptic)")
    elif phase == "Experimenter":
        print("  y = re-run Experimenter")
        print("  n = proceed to Writer stage")
    elif phase == "Writer":
        print("  y = re-run Writer")
        print("  n = proceed to Editor stage")
    else:
        print("  y = continue this stage")
        print("  n = proceed to next stage")
    print("=" * 60)
    try:
        raw = input("Enter (y/n): ").strip().lower()
    except EOFError:
        raw = "n"
    return "continue" if raw == "y" else "next"
