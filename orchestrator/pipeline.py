"""
EfficientResearch – iterative multi-agent pipeline.

Flow:
  Phase 1 · Explore   : Ideator → Scout → DeepResearcher
  Phase 2 · Review    : Skeptic ⟲ DeepResearcher  (up to MAX_REVIEW_ITER)
  Phase 3 · Experiment: Experimenter
  Phase 4 · Write     : Writer ⟲ [DeepResearcher | Experimenter]  (up to MAX_WRITE_ITER)
  Phase 5 · Edit      : Editor
  Phase 6 · PeerReview: Reviewer[MLSys|VLDB|NeurIPS|AAAI] ⟲ Writer  (up to MAX_PEER_REVIEW_ITER)

Loops trigger when:
  - Skeptic finds evidence gaps  → re-run DeepResearcher with targeted queries, then re-Skeptic
  - Writer gate fails on baselines/citations → re-run DeepResearcher (+Skeptic)
  - Writer gate fails on EVID coverage      → re-run Experimenter
  - Writer gate fails on speculation/text   → re-run Writer with fix_list only
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.state import create_initial_state, get_selected_hypotheses
from tools.io import ensure_artifacts_dirs, save_json
from tools.latex_builder import build_latex, inject_result_tables, compile_pdf
from tools.citations import save_citations_to_bib

# ── tuneable caps ─────────────────────────────────────────────
MAX_REVIEW_ITER      = 2   # Skeptic ↔ DeepResearcher loops
MAX_WRITE_ITER       = 3   # Writer revision loops
MAX_PEER_REVIEW_ITER = 3   # Reviewer ↔ Writer loops
SKEPTIC_RISK_THRESHOLD = 3  # min evidence-related risks that trigger re-research
REVIEWER_PASS_SCORE  = 4   # overall score threshold for acceptance (per venue)


# ══════════════════════════════════════════════════════════════
# Stage functions  (each updates `state` in-place and saves JSON)
# ══════════════════════════════════════════════════════════════

def _log(msg: str) -> None:
    print(f"[pipeline] {msg}", flush=True)


def _stage_ideator(state: dict, dirs: dict, topic: str, venue: str, constraints: str) -> None:
    _log("Phase 1 · Explore · Ideator …")
    from agents.ideator import run as ideator_run
    out = ideator_run({"topic": topic, "venue": venue, "constraints": constraints})
    state["hypotheses"] = out.get("hypotheses") or []
    if not state["hypotheses"]:
        _log("  Ideator returned no hypotheses – retrying with explicit fix_list …")
        out = ideator_run({
            "topic": topic, "venue": venue, "constraints": constraints,
            "fix_list": ["You MUST output at least 3 hypotheses. Empty list is invalid."],
        })
        state["hypotheses"] = out.get("hypotheses") or []
    # Propagate new fields to state
    state["paper_title"] = out.get("paper_title") or f"Research on {topic}"
    state["contribution_statement"] = out.get("contribution_statement") or ""
    state["contribution_type"] = out.get("contribution_type") or "empirical"
    save_json(state, dirs["runs"] / "01_ideator.json")
    _log(f"  → {len(state['hypotheses'])} hypotheses generated. Title: {state['paper_title']!r}")


def _stage_scout(state: dict, dirs: dict, topic: str) -> None:
    _log("Phase 1 · Explore · Scout …")
    from agents.scout import run as scout_run
    state["scout_output"] = scout_run({"topic": topic, "hypotheses": state["hypotheses"]})
    save_json(state, dirs["runs"] / "02_scout.json")
    selected_ids = (state["scout_output"] or {}).get("selected_ids") or []
    _log(f"  → selected hypotheses: {selected_ids}")


def _stage_deep_researcher(
    state: dict,
    dirs: dict,
    selected: list,
    iteration: int = 1,
    extra_queries: Optional[List[str]] = None,
) -> None:
    label = f"iter{iteration}" if iteration > 1 else ""
    _log(f"Phase 1 · Explore · DeepResearcher {label} …")
    from agents.deep_researcher import run as deep_run
    state["deep_research_output"] = deep_run({
        "hypotheses": selected,
        "scout_output": state["scout_output"],
        "contribution_statement": state.get("contribution_statement") or "",
        "extra_queries": extra_queries or [],
    })
    suffix = f"_iter{iteration}" if iteration > 1 else ""
    save_json(state, dirs["runs"] / f"03_deep_research{suffix}.json")
    bib_count = len((state["deep_research_output"] or {}).get("annotated_bib") or [])
    _log(f"  → {bib_count} annotated bib entries.")


def _stage_skeptic(
    state: dict,
    dirs: dict,
    selected: list,
    approach: str,
    iteration: int = 1,
) -> None:
    _log(f"Phase 2 · Review · Skeptic (iter {iteration}) …")
    from agents.skeptic import run as skeptic_run
    state["skeptic_output"] = skeptic_run({
        "approach_summary": approach,
        "deep_research_output": state["deep_research_output"],
        "hypotheses": selected,
        "contribution_statement": state.get("contribution_statement") or "",
    })
    state["skeptic_iteration"] = iteration
    # Skeptic refines the contribution_statement — update state if it produces one
    refined_cs = (state["skeptic_output"] or {}).get("contribution_statement")
    if refined_cs:
        state["contribution_statement"] = refined_cs
    suffix = f"_iter{iteration}" if iteration > 1 else ""
    save_json(state, dirs["runs"] / f"04_skeptic{suffix}.json")
    risks = (state["skeptic_output"] or {}).get("rejection_risks") or []
    verdict = (state["skeptic_output"] or {}).get("novelty_verdict", "?")
    _log(f"  → novelty={verdict}, {len(risks)} rejection risk(s).")


def _stage_experimenter(state: dict, dirs: dict, selected: list, iteration: int = 1) -> None:
    label = f"(iter {iteration})" if iteration > 1 else ""
    _log(f"Phase 3 · Experiment · Experimenter {label} …")
    from agents.experimenter import run as experimenter_run
    state["experimenter_output"] = experimenter_run({
        "hypotheses": selected,
        "contribution_statement": state.get("contribution_statement") or "",
        "contribution_type": state.get("contribution_type") or "empirical",
        "deep_research_output": state["deep_research_output"],
        "skeptic_output": state["skeptic_output"],
    })
    suffix = f"_iter{iteration}" if iteration > 1 else ""
    save_json(state, dirs["runs"] / f"05_experimenter{suffix}.json")
    plans = (state["experimenter_output"] or {}).get("experiment_plan") or []
    _log(f"  → {len(plans)} experiment(s) designed.")


def _stage_writer(
    state: dict,
    dirs: dict,
    topic: str,
    venue: str,
    selected: list,
    approach: str,
    iteration: int = 1,
) -> None:
    label = f"(iter {iteration})" if iteration > 1 else ""
    _log(f"Phase 4 · Write · Writer {label} …")
    from agents.writer import run as writer_run
    dr = state["deep_research_output"] or {}
    writer_input = {
        "topic": topic,
        "venue": venue,
        "paper_title": state.get("paper_title") or topic,
        "contribution_statement": state.get("contribution_statement") or "",
        "contribution_type": state.get("contribution_type") or "empirical",
        "method_outline": approach,
        "annotated_bib": dr.get("annotated_bib", []),
        "related_work_draft": dr.get("related_work_draft") or "",
        "hypotheses": selected,
        "skeptic_output": state["skeptic_output"],
        "experiment_output": state["experimenter_output"],
        "fix_list": state.get("fix_list") or [],
    }
    state["writer_output"] = writer_run(writer_input)
    # retry if almost empty
    sections_raw = (state["writer_output"] or {}).get("sections") or {}
    if sum(len(str(v)) for v in sections_raw.values()) < 200:
        _log("  Writer returned near-empty sections – retrying …")
        writer_input["fix_list"] = [
            "Previous run returned empty or nearly empty sections. "
            "You MUST write at least 2-4 substantive sentences per section; empty strings are invalid."
        ]
        state["writer_output"] = writer_run(writer_input)
    suffix = f"_iter{iteration}" if iteration > 1 else ""
    save_json(state, dirs["runs"] / f"06_writer{suffix}.json")


def _build_latex_artifacts(state: dict, dirs: dict, sections: dict = None) -> None:
    if sections is None:
        sections = (state["writer_output"] or {}).get("sections") or {}
    bib_entries = (state["deep_research_output"] or {}).get("annotated_bib") or []
    bib_keys = [b.get("key") for b in bib_entries if b.get("key")]
    result_tables = (state.get("experimenter_output") or {}).get("result_tables") or []
    sections_with_tables = inject_result_tables(sections, result_tables)
    build_latex(
        sections_with_tables, dirs["paper"], main_name="main",
        bib_keys=bib_keys,
        paper_title=state.get("paper_title") or "Research Paper",
    )
    save_citations_to_bib(bib_entries, dirs["paper"] / "references.bib")


# ══════════════════════════════════════════════════════════════
# Routing helpers
# ══════════════════════════════════════════════════════════════

def _skeptic_needs_more_evidence(skeptic_output: dict, threshold: int = SKEPTIC_RISK_THRESHOLD) -> bool:
    """Return True if Skeptic identified enough evidence-gap risks to warrant a re-research pass."""
    risks = skeptic_output.get("rejection_risks") or []
    evidence_keywords = ["missing", "no evidence", "lack", "not compared", "baseline", "no comparison", "without"]
    evidence_gaps = sum(1 for r in risks if any(k in r.lower() for k in evidence_keywords))
    return evidence_gaps >= threshold


def _classify_reviewer_feedback(reviews: List[dict]) -> Tuple[bool, bool]:
    """
    Analyse reviewer required_revisions to route revision work.
    Returns (needs_more_research, needs_more_experiments).
    Writer is always re-run in the peer-review loop.
    """
    all_revisions = " ".join(
        rev for r in reviews for rev in (r.get("required_revisions") or [])
    ).lower()
    needs_more_research    = any(k in all_revisions for k in ["baseline", "literature", "related work", "missing citation", "comparison"])
    needs_more_experiments = any(k in all_revisions for k in ["experiment", "ablation", "evaluation", "dataset", "result"])
    return needs_more_research, needs_more_experiments


def _classify_gate_failures(gate_reasons: List[str]) -> Tuple[bool, bool, bool]:
    """
    Returns (needs_research, needs_experiments, needs_rewrite).
    - needs_research   : baseline / citation coverage issues → re-run DeepResearcher (+Skeptic)
    - needs_experiments: [EVID:] coverage gap in results/experiments → re-run Experimenter
    - needs_rewrite    : missing tags / speculation / skeptic_items → re-run Writer with fix_list
    """
    joined = " ".join(gate_reasons).lower()
    # "no [cite:" or "no [evid:" → Writer didn't use tags at all → rewrite with explicit instructions
    missing_tags = "no [cite:" in joined or "no [evid:" in joined or "no [spec]" in joined
    needs_research    = ("baseline" in joined or "citation_coverage" in joined) and not missing_tags
    # Only trigger Experimenter re-run when EVID *coverage* is low (not when tags are entirely absent)
    needs_experiments = ("evid" in joined or "experiment" in joined) and not missing_tags
    needs_rewrite     = "speculation" in joined or "skeptic_items" in joined or missing_tags
    return needs_research, needs_experiments, needs_rewrite


# ══════════════════════════════════════════════════════════════
# Main pipeline
# ══════════════════════════════════════════════════════════════

def run_pipeline(
    topic: str,
    venue: str,
    artifacts_root: Optional[str] = None,
    constraints: Optional[str] = None,
) -> dict:
    if artifacts_root is None:
        artifacts_root = str(_REPO_ROOT / "artifacts")
    if constraints is None:
        constraints = venue
    dirs = ensure_artifacts_dirs(artifacts_root)
    state = create_initial_state(topic, venue, artifacts_root)
    state["loop_log"] = []   # track every loop event for transparency

    # ── Phase 1: Explore ─────────────────────────────────────
    _stage_ideator(state, dirs, topic, venue, constraints)
    _stage_scout(state, dirs, topic)
    selected = get_selected_hypotheses(state)
    _stage_deep_researcher(state, dirs, selected, iteration=1)

    # ── Phase 2: Review loop ──────────────────────────────────
    approach = "Selected hypotheses: " + json.dumps(
        [h.get("claim") for h in selected], indent=2
    )
    for review_iter in range(1, MAX_REVIEW_ITER + 1):
        _stage_skeptic(state, dirs, selected, approach, iteration=review_iter)

        novelty_verdict = (state["skeptic_output"] or {}).get("novelty_verdict", "unclear")

        if novelty_verdict == "missing":
            # Novelty gap is absent — log it prominently and add to Writer fix_list
            event = (
                f"review_iter={review_iter}: Skeptic novelty_verdict=MISSING – "
                "contribution gap not found in literature. Adding explicit fix guidance for Writer."
            )
            _log(f"  ⚠  {event}")
            state["loop_log"].append(event)
            state["fix_list"] = (state.get("fix_list") or []) + [
                "CRITICAL: Skeptic could not identify a clear novelty gap. "
                "In the intro and method sections, you MUST explicitly state what prior work CANNOT do "
                "and why your approach fills this specific gap. Cite specific papers from annotated_bib by key."
            ]

        if review_iter < MAX_REVIEW_ITER and _skeptic_needs_more_evidence(state["skeptic_output"]):
            extra_queries = (state["skeptic_output"] or {}).get("rejection_risks") or []
            event = f"review_iter={review_iter}: Skeptic found evidence gaps – re-running DeepResearcher with {len(extra_queries)} extra queries."
            _log(f"  ↩  {event}")
            state["loop_log"].append(event)
            _stage_deep_researcher(state, dirs, selected, iteration=review_iter + 1, extra_queries=extra_queries)
        else:
            if review_iter > 1:
                _log(f"  ✓ Review loop converged after {review_iter} iteration(s). novelty={novelty_verdict}")
            break

    # ── Phase 3: Experiment ───────────────────────────────────
    _stage_experimenter(state, dirs, selected, iteration=1)

    # ── Phase 4: Write loop ───────────────────────────────────
    from eval.gates import run_gates
    state["gate_results"] = state.get("gate_results") or {}

    for write_iter in range(1, MAX_WRITE_ITER + 1):
        state["fix_list"] = state.get("fix_list") or []
        _stage_writer(state, dirs, topic, venue, selected, approach, iteration=write_iter)
        gate_ok, gate_reasons = run_gates("writer", state)
        state["gate_results"][f"writer_iter{write_iter}"] = {"pass": gate_ok, "reasons": gate_reasons}

        if gate_ok or write_iter == MAX_WRITE_ITER:
            if gate_ok:
                _log(f"  ✓ Writer gates passed on iteration {write_iter}.")
            else:
                _log(f"  ⚠  Writer gates still failing after {write_iter} iteration(s) – proceeding anyway.")
            break

        # Classify failures and route to the right upstream stage
        needs_research, needs_experiments, needs_rewrite = _classify_gate_failures(gate_reasons)
        event = (
            f"write_iter={write_iter}: gates FAIL {gate_reasons} → "
            f"research={needs_research} experiments={needs_experiments} rewrite={needs_rewrite}"
        )
        _log(f"  ↩  {event}")
        state["loop_log"].append(event)
        # If tags are entirely absent, give Writer a concrete action instruction
        joined_reasons = " ".join(gate_reasons).lower()
        if "no [cite:" in joined_reasons or "no [evid:" in joined_reasons:
            bib = (state["deep_research_output"] or {}).get("annotated_bib") or []
            bib_keys_hint = ", ".join(b.get("key", "") for b in bib[:6] if b.get("key"))
            state["fix_list"] = [
                f"CRITICAL: You MUST use [CITE:key] tags in every paragraph of the intro and related_work "
                f"sections. Available bib keys: {bib_keys_hint}. "
                "Example: 'Prior work [CITE:moe2024] showed X, but lacks Y.' "
                "Do NOT write prose without citation tags — the gating system will reject your output."
            ] + gate_reasons
        else:
            state["fix_list"] = gate_reasons

        if needs_research:
            _log("     → Re-running DeepResearcher (citation / baseline gap) …")
            extra_queries = gate_reasons
            _stage_deep_researcher(state, dirs, selected, iteration=write_iter + 10, extra_queries=extra_queries)
            _log("     → Re-running Skeptic after new research …")
            _stage_skeptic(state, dirs, selected, approach, iteration=state["skeptic_iteration"] + 1)
            state["skeptic_iteration"] += 1

        if needs_experiments:
            _log("     → Re-running Experimenter (EVID coverage gap) …")
            _stage_experimenter(state, dirs, selected, iteration=write_iter + 1)

        # if only needs_rewrite, fix_list is already set → Writer will self-correct next iter

    # ── Build intermediate LaTeX ──────────────────────────────
    _build_latex_artifacts(state, dirs)

    # ── Phase 5: Edit ─────────────────────────────────────────
    _log("Phase 5 · Edit · Editor …")
    from agents.editor import run as editor_run
    sections = (state["writer_output"] or {}).get("sections") or {}
    state["editor_output"] = editor_run({
        "sections": sections,
        "contribution_statement": state.get("contribution_statement") or "",
        "paper_title": state.get("paper_title") or "",
    })
    save_json(state, dirs["runs"] / "07_editor.json")

    gate_ok_ed, gate_reasons_ed = run_gates("editor", state)
    state["gate_results"]["editor"] = {"pass": gate_ok_ed, "reasons": gate_reasons_ed}

    # ── Phase 6: Peer Review loop ─────────────────────────────
    from agents.reviewer import run_all as reviewer_run_all, all_pass, collect_revisions
    _log("Phase 6 · Peer Review …")

    for peer_iter in range(1, MAX_PEER_REVIEW_ITER + 1):
        _log(f"  Phase 6 · Reviewer (iter {peer_iter}) – running MLSys / VLDB / NeurIPS / AAAI …")
        reviews = reviewer_run_all(state)
        state["reviewer_outputs"] = reviews
        suffix = f"_iter{peer_iter}" if peer_iter > 1 else ""
        save_json(state, dirs["runs"] / f"08_review{suffix}.json")

        scores_str = ", ".join(
            f"{r['venue']}={r.get('overall', '?')}" for r in reviews
        )
        _log(f"    Scores: {scores_str}")

        if all_pass(reviews, threshold=REVIEWER_PASS_SCORE):
            _log(f"  ✓ All reviewers score ≥{REVIEWER_PASS_SCORE} – peer review passed.")
            break

        if peer_iter == MAX_PEER_REVIEW_ITER:
            _log(f"  ⚠  Peer review still failing after {peer_iter} iteration(s) – proceeding with best version.")
            break

        # Gather revision feedback and route revision work
        revision_items = collect_revisions(reviews)
        state["reviewer_fix_list"] = revision_items
        event = (
            f"peer_iter={peer_iter}: reviewer scores={scores_str} – "
            f"{len(revision_items)} revision items collected."
        )
        _log(f"  ↩  {event}")
        state["loop_log"].append(event)

        needs_more_research, needs_more_experiments = _classify_reviewer_feedback(reviews)

        if needs_more_research:
            _log("     → Re-running DeepResearcher (literature gap from reviewers) …")
            research_queries = [item for item in revision_items if any(
                k in item.lower() for k in ["baseline", "literature", "comparison", "citation"]
            )][:4]
            _stage_deep_researcher(state, dirs, selected, iteration=peer_iter + 20, extra_queries=research_queries)
            _log("     → Re-running Skeptic after new research …")
            _stage_skeptic(state, dirs, selected, approach, iteration=state["skeptic_iteration"] + 1)
            state["skeptic_iteration"] += 1

        if needs_more_experiments:
            _log("     → Re-running Experimenter (experiment gap from reviewers) …")
            _stage_experimenter(state, dirs, selected, iteration=peer_iter + 10)

        # Cap fix_list to top 5 most critical items — a longer list overwhelms the Writer
        state["fix_list"] = revision_items[:5]
        _log("     → Re-running Writer with reviewer fix_list …")
        _stage_writer(state, dirs, topic, venue, selected, approach, iteration=peer_iter + 30)

        _log("     → Re-running Editor …")
        sections = (state["writer_output"] or {}).get("sections") or {}
        state["editor_output"] = editor_run({
            "sections": sections,
            "contribution_statement": state.get("contribution_statement") or "",
            "paper_title": state.get("paper_title") or "",
        })
        save_json(state, dirs["runs"] / f"07_editor_peer{peer_iter}.json")

    # Rebuild final LaTeX from editor output
    final_sections = (state["editor_output"] or {}).get("sections") or sections
    _build_latex_artifacts(state, dirs, sections=final_sections)

    # Compile PDF (ACM sigconf double-column)
    _log("Compiling PDF (pdflatex × 4) …")
    pdf_path = compile_pdf(dirs["paper"])
    if pdf_path:
        _log(f"  ✓ PDF ready: {pdf_path}")
    else:
        _log("  ⚠  PDF compilation failed — see artifacts/paper/*.log for details.")

    _log("Done. Artifacts written.")

    return state


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="EfficientResearch iterative pipeline")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--venue", default="Workshop, 4–6 pages, double-column")
    parser.add_argument("--constraints", default=None, help="Problem description / constraints (default: venue)")
    parser.add_argument("--artifacts", default=None)
    parser.add_argument("--local", action="store_true", help="Use local LLM (vLLM)")
    parser.add_argument("--browser", action="store_true", help="Use browser-based ChatGPT (no API key needed)")
    args = parser.parse_args()

    import config
    if args.local:
        config.set_use_local_llm(True)
    if args.browser:
        config.set_use_browser_llm(True)

    artifacts_root = args.artifacts or str(_REPO_ROOT / "artifacts")
    state = run_pipeline(args.topic, args.venue, artifacts_root, constraints=args.constraints)
    dirs = ensure_artifacts_dirs(artifacts_root)

    print("\n══════════════════════════════════════════")
    print("  EfficientResearch pipeline complete")
    print("══════════════════════════════════════════")
    print(f"  Paper (LaTeX) : {dirs['paper'] / 'main.tex'}")
    pdf = dirs["paper"] / "main.pdf"
    print(f"  Paper (PDF)   : {pdf}" + (" ✓" if pdf.exists() else " (compilation failed)"))
    print(f"  References    : {dirs['paper'] / 'references.bib'}")
    print(f"  Run logs      : {dirs['runs']}")
    print(f"  Gate results  : {json.dumps(state.get('gate_results', {}), indent=4)}")
    if state.get("reviewer_outputs"):
        print("  Reviewer scores:")
        for r in state["reviewer_outputs"]:
            print(f"    • {r.get('venue')}: overall={r.get('overall')} → {r.get('recommendation')}")
    if state.get("loop_log"):
        print("  Loop events   :")
        for e in state["loop_log"]:
            print(f"    • {e}")
    print("══════════════════════════════════════════")


if __name__ == "__main__":
    main()
