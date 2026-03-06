"""
EfficientResearch – iterative multi-agent pipeline with human-in-the-loop.

Human intervention is the default at every major stage:
  - Results are written to editable Markdown files
  - User edits the Markdown, then confirms
  - Edited content is read back as stage output for the next round

Flow:
  Phase 1 · Explore   : Ideator → Scout → DeepResearcher (human review loop)
  Phase 2 · Review    : Skeptic ⟲ DeepResearcher  (up to MAX_REVIEW_ITER)
  Phase 3 · Experiment: Experimenter (human review loop)
  Phase 4 · Write     : Writer (human review loop) ⟲ gates
  Phase 5 · Edit      : Editor
  Phase 6 · PeerReview: Reviewer ⟲ Writer  (up to MAX_PEER_REVIEW_ITER)
"""
import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

from researchbot.orchestrator.state import create_initial_state, get_selected_hypotheses
from researchbot.orchestrator.human_review import (
    ensure_review_dir,
    write_ideator_report, prompt_hypothesis_selection,
    write_deep_research_report, read_deep_research_md,
    write_experimenter_report, read_experimenter_md,
    write_writer_report, read_writer_md,
    prompt_edit_and_confirm,
)
from researchbot.tools.io import ensure_artifacts_dirs, load_state_from_runs, save_json
from researchbot.tools.latex_builder import build_latex, inject_result_tables, compile_pdf
from researchbot.tools.citations import save_citations_to_bib

# ── tuneable caps (override via env vars) ─────────────────────
MAX_REVIEW_ITER      = int(os.environ.get("RESEARCHBOT_MAX_REVIEW_ITER", "2"))
MAX_WRITE_ITER       = int(os.environ.get("RESEARCHBOT_MAX_WRITE_ITER", "3"))
MAX_PEER_REVIEW_ITER = int(os.environ.get("RESEARCHBOT_MAX_PEER_REVIEW_ITER", "3"))
SKEPTIC_RISK_THRESHOLD = int(os.environ.get("RESEARCHBOT_SKEPTIC_RISK_THRESHOLD", "3"))
REVIEWER_PASS_SCORE  = int(os.environ.get("RESEARCHBOT_REVIEWER_PASS_SCORE", "4"))


# ══════════════════════════════════════════════════════════════
# Stage functions
# ══════════════════════════════════════════════════════════════

def _log(msg: str) -> None:
    print(f"[pipeline] {msg}", flush=True)


def _stage_ideator(state: dict, dirs: dict, topic: str, venue: str, constraints: str) -> None:
    _log("Phase 1 · Explore · Ideator ...")
    from researchbot.agents.ideator import run as ideator_run
    ideator_input = {"topic": topic, "venue": venue, "constraints": constraints}
    if state.get("retrieved_memory"):
        ideator_input["retrieved_memory"] = state["retrieved_memory"]
    if state.get("preferred_focus"):
        ideator_input["preferred_focus"] = state["preferred_focus"]
    out = ideator_run(ideator_input)
    state["hypotheses"] = out.get("hypotheses") or []
    if not state["hypotheses"]:
        _log("  Ideator returned no hypotheses - retrying ...")
        out = ideator_run({
            "topic": topic, "venue": venue, "constraints": constraints,
            "fix_list": ["You MUST output at least 3 hypotheses. Empty list is invalid."],
        })
        state["hypotheses"] = out.get("hypotheses") or []
    state["related_work_summary"] = out.get("related_work_summary") or ""
    state["unsolved_problems"] = out.get("unsolved_problems") or []
    state["research_worthy"] = out.get("research_worthy") or []
    state["proposals"] = out.get("proposals") or []
    state["paper_title"] = out.get("paper_title") or f"Research on {topic}"
    state["contribution_statement"] = out.get("contribution_statement") or ""
    state["contribution_type"] = out.get("contribution_type") or "empirical"
    save_json(state, dirs["runs"] / "01_ideator.json")
    _log(f"  -> {len(state['hypotheses'])} hypotheses, title: {state['paper_title']!r}")


def _stage_scout(state: dict, dirs: dict, topic: str, preferred_focus: Optional[str] = None) -> None:
    _log("Phase 1 · Explore · Scout ...")
    from researchbot.agents.scout import run as scout_run
    scout_input = {"topic": topic, "hypotheses": state["hypotheses"]}
    if preferred_focus:
        scout_input["preferred_focus"] = preferred_focus
    state["scout_output"] = scout_run(scout_input)
    save_json(state, dirs["runs"] / "02_scout.json")
    selected_ids = (state["scout_output"] or {}).get("selected_ids") or []
    _log(f"  -> selected hypotheses: {selected_ids}")


def _stage_deep_researcher(
    state: dict, dirs: dict, selected: list,
    iteration: int = 1, extra_queries: Optional[List[str]] = None,
) -> None:
    label = f"iter{iteration}" if iteration > 1 else ""
    _log(f"Phase 1 · Explore · DeepResearcher {label} ...")
    from researchbot.agents.deep_researcher import run as deep_run
    state["deep_research_output"] = deep_run({
        "hypotheses": selected,
        "scout_output": state["scout_output"],
        "contribution_statement": state.get("contribution_statement") or "",
        "extra_queries": extra_queries or [],
    })
    suffix = f"_iter{iteration}" if iteration > 1 else ""
    save_json(state, dirs["runs"] / f"03_deep_research{suffix}.json")
    bib_count = len((state["deep_research_output"] or {}).get("annotated_bib") or [])
    _log(f"  -> {bib_count} annotated bib entries.")


def _stage_skeptic(
    state: dict, dirs: dict, selected: list, approach: str, iteration: int = 1,
) -> None:
    _log(f"Phase 2 · Review · Skeptic (iter {iteration}) ...")
    from researchbot.agents.skeptic import run as skeptic_run
    state["skeptic_output"] = skeptic_run({
        "approach_summary": approach,
        "deep_research_output": state["deep_research_output"],
        "hypotheses": selected,
        "contribution_statement": state.get("contribution_statement") or "",
    })
    state["skeptic_iteration"] = iteration
    refined_cs = (state["skeptic_output"] or {}).get("contribution_statement")
    if refined_cs:
        state["contribution_statement"] = refined_cs
    suffix = f"_iter{iteration}" if iteration > 1 else ""
    save_json(state, dirs["runs"] / f"04_skeptic{suffix}.json")
    risks = (state["skeptic_output"] or {}).get("rejection_risks") or []
    verdict = (state["skeptic_output"] or {}).get("novelty_verdict", "?")
    _log(f"  -> novelty={verdict}, {len(risks)} rejection risk(s).")


def _stage_experimenter(state: dict, dirs: dict, selected: list, iteration: int = 1) -> None:
    label = f"(iter {iteration})" if iteration > 1 else ""
    _log(f"Phase 3 · Experiment · Experimenter {label} ...")
    from researchbot.agents.experimenter import run as experimenter_run
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
    _log(f"  -> {len(plans)} experiment(s) designed.")


def _stage_writer(
    state: dict, dirs: dict, topic: str, venue: str,
    selected: list, approach: str, iteration: int = 1,
    sections_to_write: Optional[List[str]] = None,
    existing_sections: Optional[dict] = None,
) -> None:
    label = f"(iter {iteration})" if iteration > 1 else ""
    if sections_to_write:
        _log(f"Phase 4 · Write · Writer {label} (sections: {', '.join(sections_to_write)}) ...")
    else:
        _log(f"Phase 4 · Write · Writer {label} ...")
    from researchbot.agents.writer import run as writer_run
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
    if sections_to_write:
        writer_input["sections_to_write"] = sections_to_write
    if existing_sections:
        writer_input["existing_sections"] = existing_sections
    state["writer_output"] = writer_run(writer_input)
    # retry if almost empty
    sections_raw = (state["writer_output"] or {}).get("sections") or {}
    if sum(len(str(v)) for v in sections_raw.values()) < 200:
        _log("  Writer returned near-empty sections - retrying ...")
        writer_input["fix_list"] = [
            "Previous run returned empty or nearly empty sections. "
            "You MUST write at least 2-4 substantive sentences per section."
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
    risks = skeptic_output.get("rejection_risks") or []
    evidence_keywords = ["missing", "no evidence", "lack", "not compared", "baseline", "no comparison", "without"]
    evidence_gaps = sum(1 for r in risks if any(k in r.lower() for k in evidence_keywords))
    return evidence_gaps >= threshold


def _classify_reviewer_feedback(reviews: List[dict]) -> Tuple[bool, bool]:
    all_revisions = " ".join(
        rev for r in reviews for rev in (r.get("required_revisions") or [])
    ).lower()
    needs_more_research = any(k in all_revisions for k in ["baseline", "literature", "related work", "missing citation", "comparison"])
    needs_more_experiments = any(k in all_revisions for k in ["experiment", "ablation", "evaluation", "dataset", "result"])
    return needs_more_research, needs_more_experiments


def _classify_gate_failures(gate_reasons: List[str]) -> Tuple[bool, bool, bool]:
    joined = " ".join(gate_reasons).lower()
    missing_tags = "no [cite:" in joined or "no [evid:" in joined or "no [spec]" in joined
    needs_research = ("baseline" in joined or "citation_coverage" in joined) and not missing_tags
    needs_experiments = ("evid" in joined or "experiment" in joined) and not missing_tags
    needs_rewrite = "speculation" in joined or "skeptic_items" in joined or missing_tags
    return needs_research, needs_experiments, needs_rewrite


# ══════════════════════════════════════════════════════════════
# Main pipeline (human-in-the-loop is always on)
# ══════════════════════════════════════════════════════════════

def _detect_resume_stage(runs_dir) -> Optional[str]:
    from pathlib import Path
    runs = Path(runs_dir)
    stage_order = [
        ("07_editor",        "peer_review"),
        ("06_writer",        "editor"),
        ("05_experimenter",  "writer"),
        ("04_skeptic",       "experimenter"),
        ("03_deep_research", "skeptic"),
        ("02_scout",         "deep_researcher"),
        ("01_ideator",       "scout"),
    ]
    for prefix, next_stage in stage_order:
        if list(runs.glob(prefix + "*.json")):
            return next_stage
    return None


def run_pipeline(
    topic: str,
    venue: str,
    artifacts_root: Optional[str] = None,
    constraints: Optional[str] = None,
    sections: Optional[List[str]] = None,
    focus: Optional[str] = None,
    resume: bool = False,
) -> dict:
    if artifacts_root is None:
        artifacts_root = str(Path.cwd())
    if constraints is None:
        constraints = venue
    dirs = ensure_artifacts_dirs(artifacts_root)
    state = create_initial_state(topic, venue, artifacts_root)
    state["loop_log"] = []
    review_dir = ensure_review_dir(artifacts_root)

    # ── Resume ──
    resume_from = None
    if resume:
        resume_from = _detect_resume_stage(dirs["runs"])
        if resume_from:
            loaded = load_state_from_runs(dirs["runs"])
            if loaded:
                # Warn if topic/venue changed since last run
                prev_topic = loaded.get("topic", "")
                prev_venue = loaded.get("venue", "")
                if prev_topic and prev_topic != topic:
                    _log(f"WARNING: Topic changed since last run (was: {prev_topic!r}). Results may be incoherent.")
                if prev_venue and prev_venue != venue:
                    _log(f"WARNING: Venue changed since last run (was: {prev_venue!r}).")
                state.update(loaded)
                state["topic"] = topic
                state["venue"] = venue
                state["loop_log"] = state.get("loop_log") or []
                _log(f"Resuming from stage: {resume_from}")
            else:
                _log("Resume requested but could not load prior state. Starting fresh.")
                resume_from = None
        else:
            _log("Resume requested but no prior run found. Starting fresh.")
    if focus:
        state["preferred_focus"] = focus.strip().lower()
        _log(f"Focus: {state['preferred_focus']}")

    # RAG memory
    try:
        from researchbot.tools.rag import query, format_retrieved_for_prompt
        hits = query(topic, k=5, artifacts_root=artifacts_root)
        if hits:
            state["retrieved_memory"] = format_retrieved_for_prompt(hits, max_chars=2500)
            _log(f"RAG: injected {len(hits)} memory fragments.")
    except Exception:
        state["retrieved_memory"] = ""

    from researchbot import config
    if getattr(config, "USE_BROWSER_LLM", False):
        from tools import browser_llm
        browser_llm.start_browser_session()

    # ── Partial run: only regenerate given sections ──
    if sections:
        loaded = load_state_from_runs(dirs["runs"])
        if not loaded:
            _log("Cannot run partial: no prior run found. Run full pipeline first.")
            return state
        state.update(loaded)
        state["topic"] = topic
        state["venue"] = venue
        state["loop_log"] = state.get("loop_log") or []
        _log(f"Partial run: only sections {sections}.")
        existing_sections = (state.get("writer_output") or {}).get("sections") or {}
        selected = get_selected_hypotheses(state)
        approach = "Selected hypotheses: " + json.dumps([h.get("claim") for h in selected], indent=2)
        _stage_writer(state, dirs, topic, venue, selected, approach, iteration=1,
                      sections_to_write=sections, existing_sections=existing_sections)
        save_json(state, dirs["runs"] / "06_writer_partial.json")
        _build_latex_artifacts(state, dirs)
        _log("Phase 5 · Edit · Editor ...")
        from researchbot.agents.editor import run as editor_run
        sections_dict = (state["writer_output"] or {}).get("sections") or {}
        state["editor_output"] = editor_run({
            "sections": sections_dict,
            "contribution_statement": state.get("contribution_statement") or "",
            "paper_title": state.get("paper_title") or "",
        })
        save_json(state, dirs["runs"] / "07_editor.json")
        final_sections = (state["editor_output"] or {}).get("sections") or sections_dict
        _build_latex_artifacts(state, dirs, sections=final_sections)
        _log("Compiling PDF ...")
        compile_pdf(dirs["paper"])
        _log("Done (partial).")
        return state

    # ── Resume skip helper ──
    _STAGE_ORDER = ["ideator", "scout", "deep_researcher", "skeptic", "experimenter", "writer", "editor", "peer_review"]
    def _should_skip(stage_name: str) -> bool:
        if not resume_from:
            return False
        return _STAGE_ORDER.index(stage_name) < _STAGE_ORDER.index(resume_from)

    # ══════════════════════════════════════════════════════════
    # Phase 1: Explore
    # ══════════════════════════════════════════════════════════
    if _should_skip("ideator"):
        _log("Phase 1 · Ideator ... (skipped, loaded from checkpoint)")
    else:
        _stage_ideator(state, dirs, topic, venue, constraints)

    # Human: write ideator report, let user select hypotheses
    write_ideator_report(state, review_dir)
    _log(f"  Ideator report: {review_dir / '01_ideator.md'}")
    selected_ids = prompt_hypothesis_selection(state)
    if selected_ids:
        state["scout_output"] = (state.get("scout_output") or {}) | {"selected_ids": selected_ids}
        _log(f"  Human selected: {selected_ids}")

    # Still run Scout for related_work if needed
    if not (state.get("scout_output") or {}).get("related_work"):
        if _should_skip("scout"):
            _log("Phase 1 · Scout ... (skipped, loaded from checkpoint)")
        else:
            _stage_scout(state, dirs, topic, state.get("preferred_focus") or None)
            state["scout_output"] = (state["scout_output"] or {}) | {"selected_ids": selected_ids}

    selected = get_selected_hypotheses(state)
    if not selected and state.get("hypotheses"):
        selected = state["hypotheses"][:2]
        state["scout_output"] = (state.get("scout_output") or {}) | {
            "selected_ids": [(state["hypotheses"][i].get("id") or f"H{i+1}") for i in range(min(2, len(state["hypotheses"])))]
        }
        selected = get_selected_hypotheses(state)

    # ── DeepResearch: human review loop ──
    if _should_skip("deep_researcher"):
        _log("Phase 1 · DeepResearcher ... (skipped, loaded from checkpoint)")
    else:
        deep_round = 1
        while True:
            _stage_deep_researcher(state, dirs, selected, iteration=deep_round)
            md_path = write_deep_research_report(state, review_dir, deep_round)
            _log(f"  DeepResearch round {deep_round}: {md_path}")
            choice = prompt_edit_and_confirm("DeepResearch", md_path, round_n=deep_round)
            if choice == "next":
                # Read back any human edits before proceeding
                edited = read_deep_research_md(review_dir, deep_round)
                if edited:
                    state["deep_research_output"] = edited
                    _log("  Read back human edits from DeepResearch MD.")
                break
            # Read back edits for next round
            edited = read_deep_research_md(review_dir, deep_round)
            if edited:
                state["deep_research_output"] = edited
                _log("  Read back human edits from DeepResearch MD.")
            deep_round += 1

    # ══════════════════════════════════════════════════════════
    # Phase 2: Skeptic review loop
    # ══════════════════════════════════════════════════════════
    approach = "Selected hypotheses: " + json.dumps(
        [h.get("claim") for h in selected], indent=2
    )
    if _should_skip("skeptic"):
        _log("Phase 2 · Skeptic ... (skipped, loaded from checkpoint)")
    else:
        for review_iter in range(1, MAX_REVIEW_ITER + 1):
            _stage_skeptic(state, dirs, selected, approach, iteration=review_iter)

            novelty_verdict = (state["skeptic_output"] or {}).get("novelty_verdict", "unclear")
            if novelty_verdict == "missing":
                event = f"review_iter={review_iter}: Skeptic novelty_verdict=MISSING"
                _log(f"  ! {event}")
                state["loop_log"].append(event)
                state["fix_list"] = (state.get("fix_list") or []) + [
                    "CRITICAL: Skeptic could not identify a clear novelty gap. "
                    "In the intro and method sections, explicitly state what prior work CANNOT do "
                    "and why your approach fills this specific gap."
                ]

            if review_iter < MAX_REVIEW_ITER and _skeptic_needs_more_evidence(state["skeptic_output"]):
                extra_queries = (state["skeptic_output"] or {}).get("rejection_risks") or []
                event = f"review_iter={review_iter}: Skeptic found evidence gaps - re-running DeepResearcher."
                _log(f"  <- {event}")
                state["loop_log"].append(event)
                _stage_deep_researcher(state, dirs, selected, iteration=review_iter + 1, extra_queries=extra_queries)
            else:
                if review_iter > 1:
                    _log(f"  OK Review loop converged after {review_iter} iteration(s).")
                break

    # ══════════════════════════════════════════════════════════
    # Phase 3: Experimenter (human review loop)
    # ══════════════════════════════════════════════════════════
    if _should_skip("experimenter"):
        _log("Phase 3 · Experiment ... (skipped, loaded from checkpoint)")
    else:
        exp_iter = 1
        while True:
            _stage_experimenter(state, dirs, selected, iteration=exp_iter)
            md_path = write_experimenter_report(state, review_dir)
            _log(f"  Experimenter report: {md_path}")
            choice = prompt_edit_and_confirm("Experimenter", md_path)
            if choice == "next":
                edited = read_experimenter_md(review_dir)
                if edited:
                    state["experimenter_output"] = edited
                    _log("  Read back human edits from Experimenter MD.")
                break
            edited = read_experimenter_md(review_dir)
            if edited:
                state["experimenter_output"] = edited
                _log("  Read back human edits from Experimenter MD.")
            exp_iter += 1

    # ══════════════════════════════════════════════════════════
    # Phase 4: Writer (human review loop + gates)
    # ══════════════════════════════════════════════════════════
    from researchbot.eval.gates import run_gates
    state["gate_results"] = state.get("gate_results") or {}

    for write_iter in range(1, MAX_WRITE_ITER + 1):
        state["fix_list"] = state.get("fix_list") or []
        _stage_writer(state, dirs, topic, venue, selected, approach, iteration=write_iter)
        gate_ok, gate_reasons = run_gates("writer", state)
        state["gate_results"][f"writer_iter{write_iter}"] = {"pass": gate_ok, "reasons": gate_reasons}

        # Human review: write MD, let user edit, read back
        md_path = write_writer_report(state, review_dir)
        _log(f"  Writer report: {md_path}")
        if gate_ok:
            _log(f"  OK Writer gates passed on iteration {write_iter}.")
        else:
            _log(f"  ! Writer gates failed: {gate_reasons}")

        choice = prompt_edit_and_confirm("Writer", md_path)
        if choice == "next":
            # Read back human edits
            edited_sections = read_writer_md(review_dir)
            if edited_sections:
                state["writer_output"] = (state.get("writer_output") or {}) | {"sections": edited_sections}
                _log("  Read back human edits from Writer MD.")
            break

        # Read back edits for next iteration
        edited_sections = read_writer_md(review_dir)
        if edited_sections:
            state["writer_output"] = (state.get("writer_output") or {}) | {"sections": edited_sections}
            _log("  Read back human edits from Writer MD.")

        if gate_ok or write_iter == MAX_WRITE_ITER:
            if not gate_ok:
                _log(f"  ! Writer gates still failing after {write_iter} iteration(s) - proceeding.")
            break

        # Classify failures and route
        needs_research, needs_experiments, needs_rewrite = _classify_gate_failures(gate_reasons)
        event = f"write_iter={write_iter}: gates FAIL -> research={needs_research} experiments={needs_experiments} rewrite={needs_rewrite}"
        _log(f"  <- {event}")
        state["loop_log"].append(event)

        joined_reasons = " ".join(gate_reasons).lower()
        if "no [cite:" in joined_reasons or "no [evid:" in joined_reasons:
            bib = (state["deep_research_output"] or {}).get("annotated_bib") or []
            bib_keys_hint = ", ".join(b.get("key", "") for b in bib[:6] if b.get("key"))
            state["fix_list"] = [
                f"CRITICAL: Use [CITE:key] tags in intro and related_work. Available keys: {bib_keys_hint}."
            ] + gate_reasons
        else:
            state["fix_list"] = gate_reasons

        if needs_research:
            _log("     -> Re-running DeepResearcher (citation/baseline gap) ...")
            _stage_deep_researcher(state, dirs, selected, iteration=write_iter + 10, extra_queries=gate_reasons)
            _log("     -> Re-running Skeptic ...")
            _stage_skeptic(state, dirs, selected, approach, iteration=state["skeptic_iteration"] + 1)
            state["skeptic_iteration"] += 1

        if needs_experiments:
            _log("     -> Re-running Experimenter (EVID coverage gap) ...")
            _stage_experimenter(state, dirs, selected, iteration=write_iter + 1)

    # ── Build intermediate LaTeX ──
    _build_latex_artifacts(state, dirs)

    # ══════════════════════════════════════════════════════════
    # Phase 5: Editor
    # ══════════════════════════════════════════════════════════
    _log("Phase 5 · Edit · Editor ...")
    from researchbot.agents.editor import run as editor_run
    sections = (state["writer_output"] or {}).get("sections") or {}
    state["editor_output"] = editor_run({
        "sections": sections,
        "contribution_statement": state.get("contribution_statement") or "",
        "paper_title": state.get("paper_title") or "",
    })
    save_json(state, dirs["runs"] / "07_editor.json")

    gate_ok_ed, gate_reasons_ed = run_gates("editor", state)
    state["gate_results"]["editor"] = {"pass": gate_ok_ed, "reasons": gate_reasons_ed}

    # ══════════════════════════════════════════════════════════
    # Phase 6: Peer Review loop
    # ══════════════════════════════════════════════════════════
    from researchbot.agents.reviewer import run_all as reviewer_run_all, all_pass, collect_revisions
    _log("Phase 6 · Peer Review ...")

    for peer_iter in range(1, MAX_PEER_REVIEW_ITER + 1):
        _log(f"  Reviewer (iter {peer_iter}) ...")
        reviews = reviewer_run_all(state)
        state["reviewer_outputs"] = reviews
        suffix = f"_iter{peer_iter}" if peer_iter > 1 else ""
        save_json(state, dirs["runs"] / f"08_review{suffix}.json")

        scores_str = ", ".join(f"{r['venue']}={r.get('overall', '?')}" for r in reviews)
        _log(f"    Scores: {scores_str}")

        if all_pass(reviews, threshold=REVIEWER_PASS_SCORE):
            _log(f"  OK All reviewers score >= {REVIEWER_PASS_SCORE} - peer review passed.")
            break

        if peer_iter == MAX_PEER_REVIEW_ITER:
            _log(f"  ! Peer review still failing after {peer_iter} iteration(s) - proceeding.")
            break

        revision_items = collect_revisions(reviews)
        state["reviewer_fix_list"] = revision_items
        event = f"peer_iter={peer_iter}: scores={scores_str}, {len(revision_items)} revisions."
        _log(f"  <- {event}")
        state["loop_log"].append(event)

        needs_more_research, needs_more_experiments = _classify_reviewer_feedback(reviews)

        if needs_more_research:
            _log("     -> Re-running DeepResearcher (literature gap) ...")
            research_queries = [item for item in revision_items if any(
                k in item.lower() for k in ["baseline", "literature", "comparison", "citation"]
            )][:4]
            _stage_deep_researcher(state, dirs, selected, iteration=peer_iter + 20, extra_queries=research_queries)
            _log("     -> Re-running Skeptic ...")
            _stage_skeptic(state, dirs, selected, approach, iteration=state["skeptic_iteration"] + 1)
            state["skeptic_iteration"] += 1

        if needs_more_experiments:
            _log("     -> Re-running Experimenter (experiment gap) ...")
            _stage_experimenter(state, dirs, selected, iteration=peer_iter + 10)

        state["fix_list"] = revision_items[:5]
        _log("     -> Re-running Writer with reviewer fix_list ...")
        _stage_writer(state, dirs, topic, venue, selected, approach, iteration=peer_iter + 30)

        _log("     -> Re-running Editor ...")
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

    # Compile PDF
    _log("Compiling PDF ...")
    pdf_path = compile_pdf(dirs["paper"])
    if pdf_path:
        _log(f"  OK PDF ready: {pdf_path}")
    else:
        _log("  ! PDF compilation failed - see artifacts/paper/*.log")

    _log("Done. Artifacts written.")

    # Index into RAG
    try:
        from researchbot.tools.rag import index_run_artifacts
        n = index_run_artifacts(dirs["runs"], artifacts_root=artifacts_root)
        if n > 0:
            _log(f"RAG: indexed {n} fragments.")
    except Exception as e:
        _log(f"RAG index skipped: {e}")

    return state
