"""ResearchBot CLI entry point."""
import argparse
import json
import sys
from pathlib import Path


INPUT_TEMPLATE = """# ResearchBot Input

Topic: <your research topic here>
Venue: Workshop, 4-6 pages, double-column

# Optional fields:
# Constraints: <problem constraints>
# Sections: experiments,results,conclusion   (only regenerate these sections)
# Focus: system                              (system | theory | empirical | analysis)
"""


def cmd_init(args):
    """Create input.md template in CWD."""
    target = Path.cwd() / "input.md"
    if target.exists() and not args.force:
        print(f"input.md already exists. Use --force to overwrite.")
        sys.exit(1)
    target.write_text(INPUT_TEMPLATE, encoding="utf-8")
    print(f"Created {target}")
    print("Edit it with your research topic, then run: researchbot run")


def _parse_field(text: str, key: str) -> str:
    """Parse 'Key: value' from input.md content."""
    import re
    pattern = rf"^#*\s*{re.escape(key)}\s*:\s*(.+)"
    m = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def cmd_run(args):
    """Run the research pipeline."""
    # Determine topic/venue from args or input.md
    topic = args.topic
    venue = args.venue
    constraints = args.constraints
    sections_arg = args.sections
    focus = args.focus

    if not topic:
        input_file = Path.cwd() / "input.md"
        if not input_file.exists():
            print("No --topic provided and no input.md found in current directory.")
            print("Run 'researchbot init' to create one, or pass --topic directly.")
            sys.exit(1)
        text = input_file.read_text(encoding="utf-8")
        topic = _parse_field(text, "Topic")
        if not topic:
            # Fallback: first non-empty, non-comment line
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    topic = line
                    break
        if not topic:
            print("No Topic found in input.md. Add a line like: Topic: your research topic")
            sys.exit(1)
        if not venue:
            venue = _parse_field(text, "Venue") or "Workshop, 4-6 pages, double-column"
        if not constraints:
            constraints = _parse_field(text, "Constraints") or None
        if not sections_arg:
            sections_arg = _parse_field(text, "Sections") or None
        if not focus:
            focus = _parse_field(text, "Focus") or None

    if not venue:
        venue = "Workshop, 4-6 pages, double-column"

    artifacts_root = str(Path.cwd())

    print("==============================================")
    print("  ResearchBot - Multi-Agent Research Pipeline")
    print("==============================================")
    print(f"  Topic:    {topic}")
    print(f"  Venue:    {venue}")
    if constraints:
        print(f"  Constraints: {constraints}")
    if sections_arg:
        print(f"  Sections: {sections_arg}")
    if focus:
        print(f"  Focus: {focus}")
    print(f"  Output:   {artifacts_root}")
    mode = "Browser (Playwright)" if args.browser else "API"
    print(f"  LLM mode: {mode}")
    print("==============================================")

    # Configure browser mode
    from researchbot import config
    if args.browser:
        config.set_use_browser_llm(True)

    sections_list = None
    if sections_arg:
        sections_list = [s.strip() for s in sections_arg.split(",") if s.strip()]

    from researchbot.orchestrator.pipeline import run_pipeline
    try:
        state = run_pipeline(
            topic, venue, artifacts_root,
            constraints=constraints,
            sections=sections_list,
            focus=focus,
            resume=args.resume,
        )
    finally:
        if args.browser:
            try:
                from researchbot.tools import browser_llm
                browser_llm.end_browser_session()
            except Exception:
                pass

    from researchbot.tools.io import ensure_artifacts_dirs
    dirs = ensure_artifacts_dirs(artifacts_root)

    print("\n==========================================")
    print("  ResearchBot pipeline complete")
    print("==========================================")
    print(f"  Paper (LaTeX) : {dirs['paper'] / 'main.tex'}")
    pdf = dirs["paper"] / "main.pdf"
    print(f"  Paper (PDF)   : {pdf}" + (" OK" if pdf.exists() else " (compilation failed)"))
    print(f"  References    : {dirs['paper'] / 'references.bib'}")
    print(f"  Run logs      : {dirs['runs']}")
    print(f"  Review MDs    : {Path(artifacts_root) / 'review'}")
    if state.get("reviewer_outputs"):
        print("  Reviewer scores:")
        for r in state["reviewer_outputs"]:
            print(f"    - {r.get('venue')}: overall={r.get('overall')} -> {r.get('recommendation')}")
    print("==========================================")


def main():
    parser = argparse.ArgumentParser(
        prog="researchbot",
        description="ResearchBot: Multi-agent research automation with human-in-the-loop",
    )
    subparsers = parser.add_subparsers(dest="command")

    # init
    init_parser = subparsers.add_parser("init", help="Create input.md template in current directory")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing input.md")

    # run
    run_parser = subparsers.add_parser("run", help="Run the research pipeline")
    run_parser.add_argument("--topic", default=None, help="Research topic (overrides input.md)")
    run_parser.add_argument("--venue", default=None, help="Target venue (default: Workshop, 4-6 pages)")
    run_parser.add_argument("--constraints", default=None, help="Problem constraints")
    run_parser.add_argument("--browser", action="store_true", help="Use browser-based ChatGPT (no API key needed)")
    run_parser.add_argument("--sections", default=None, help="Comma-separated sections to regenerate only")
    run_parser.add_argument("--focus", default=None, help="Research focus: system | theory | empirical | analysis")
    run_parser.add_argument("--resume", action="store_true", help="Resume from last completed stage")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
