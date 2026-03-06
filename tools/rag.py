"""Local RAG: index run artifacts for long-term memory; query by topic when needed.

Usage:
  - After a run (or on demand): index_run_artifacts(artifacts/runs) to chunk and embed 01_ideator..06_writer.
  - When starting a run or in an agent: query(topic, k=5) to get relevant past snippets to inject into prompts.

Requires: chromadb, sentence-transformers (see requirements.txt).
"""
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_RAG_DIR_ENV = "EFFICIENT_RESEARCH_RAG_DIR"
_DEFAULT_RAG_DIR = "artifacts/rag"
_COLLECTION_NAME = "researchbot"


def _get_rag_dir(artifacts_root: Optional[str] = None) -> Path:
    d = os.environ.get(_RAG_DIR_ENV, "").strip()
    if d:
        return Path(d).expanduser().resolve()
    if artifacts_root:
        return Path(artifacts_root) / "rag"
    return Path(_DEFAULT_RAG_DIR).resolve()


def _get_client(rag_dir: Path):
    import chromadb
    from chromadb.config import Settings
    return chromadb.PersistentClient(path=str(rag_dir), settings=Settings(anonymized_telemetry=False))


def _get_embedding_function():
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        return SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2",
            normalize_embeddings=True,
        )
    except Exception:
        return None


def _ensure_collection(rag_dir: Path):
    client = _get_client(rag_dir)
    ef = _get_embedding_function()
    if ef is None:
        raise RuntimeError(
            "RAG 需要 chromadb 与 sentence-transformers。请执行: pip install chromadb sentence-transformers"
        )
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=ef,
        metadata={"description": "ResearchBot run artifacts"},
    )


def _chunk_state_to_documents(state: Dict[str, Any], source: str, run_id: str) -> List[Dict[str, Any]]:
    """Turn pipeline state (or a single stage payload) into list of {text, metadata} for indexing."""
    docs = []
    # Hypotheses
    for i, h in enumerate(state.get("hypotheses") or []):
        if isinstance(h, dict):
            text = f"Hypothesis: {h.get('claim', '')} Evidence: {h.get('evidence', '')} ID: {h.get('id', '')}"
            if text.strip():
                docs.append({"text": text, "source": source, "stage": "hypotheses", "run_id": run_id})
    # Ideator four-step (related work, unsolved, research-worthy, proposals)
    rw_sum = state.get("related_work_summary") or ""
    if rw_sum.strip():
        docs.append({"text": f"Related work summary: {rw_sum[:1500]}", "source": source, "stage": "ideator_related_work", "run_id": run_id})
    for i, u in enumerate(state.get("unsolved_problems") or [])[:5]:
        if isinstance(u, dict) and (u.get("problem") or u.get("context")):
            docs.append({"text": f"Unsolved: {u.get('problem', '')} — {u.get('context', '')}", "source": source, "stage": "ideator_unsolved", "run_id": run_id})
    for i, r in enumerate(state.get("research_worthy") or [])[:5]:
        if isinstance(r, dict) and (r.get("problem") or r.get("rationale")):
            docs.append({"text": f"Research-worthy: {r.get('problem', '')} — {r.get('rationale', '')}", "source": source, "stage": "ideator_research_worthy", "run_id": run_id})
    for i, p in enumerate(state.get("proposals") or [])[:4]:
        if isinstance(p, dict) and (p.get("idea") or p.get("motivation")):
            ch = p.get("challenges") or []
            ch_str = "; ".join(str(c) for c in ch[:5]) if isinstance(ch, list) else str(ch)
            docs.append({"text": f"Proposal: {p.get('motivation', '')} Idea: {p.get('idea', '')} Challenges: {ch_str}", "source": source, "stage": "ideator_proposal", "run_id": run_id})
    # Contribution
    cs = state.get("contribution_statement") or state.get("paper_title") or ""
    if cs.strip():
        docs.append({"text": f"Contribution / title: {cs}", "source": source, "stage": "contribution", "run_id": run_id})
    # Scout
    scout = state.get("scout_output") or {}
    if scout:
        rw = scout.get("related_work") or ""
        if rw.strip():
            docs.append({"text": f"Related work: {rw[:2000]}", "source": source, "stage": "scout", "run_id": run_id})
    # Deep research
    deep = state.get("deep_research_output") or {}
    if deep:
        gap = deep.get("gap_summary") or ""
        if gap.strip():
            docs.append({"text": f"Gap summary: {gap}", "source": source, "stage": "deep_research", "run_id": run_id})
    # Skeptic
    skeptic = state.get("skeptic_output") or {}
    if skeptic:
        risks = skeptic.get("rejection_risks") or []
        req_exp = skeptic.get("required_experiments") or []
        t = "Risks: " + " | ".join(str(r) for r in risks[:10]) + " Required experiments: " + " | ".join(str(e) for e in req_exp[:10])
        if t.strip():
            docs.append({"text": t, "source": source, "stage": "skeptic", "run_id": run_id})
    # Experimenter
    exp = state.get("experimenter_output") or {}
    if exp:
        plan = exp.get("experiment_plan") or []
        for i, p in enumerate(plan[:5]):
            if isinstance(p, dict):
                text = f"Experiment: {p.get('name', '')} {p.get('expected_outcome', '')}"
                if text.strip():
                    docs.append({"text": text, "source": source, "stage": "experimenter", "run_id": run_id})
    # Writer sections (summary)
    wo = state.get("writer_output") or {}
    sections = wo.get("sections") or {}
    for key, val in list(sections.items())[:5]:
        if val and isinstance(val, str) and len(val) > 100:
            docs.append({
                "text": f"Section {key}: {val[:1500]}",
                "source": source,
                "stage": "writer",
                "run_id": run_id,
            })
    return docs


def index_run_artifacts(
    runs_dir: str | Path,
    artifacts_root: Optional[str] = None,
    run_id: Optional[str] = None,
) -> int:
    """Load state from runs_dir (01_ideator..06_writer), chunk into documents, add to RAG. Returns count added."""
    from tools.io import load_state_from_runs, load_json
    runs_path = Path(runs_dir)
    if run_id is None:
        run_id = f"run_{int(time.time())}"
    state = load_state_from_runs(runs_path)
    if not state:
        # Fallback: load each file and merge into a single "state" for chunking
        state = {}
        for name in ["01_ideator", "02_scout", "03_deep_research", "04_skeptic", "05_experimenter", "06_writer"]:
            for p in sorted(runs_path.glob(name + "*.json")):
                data = load_json(p)
                if data:
                    state.update(data)
                break
    if not state:
        return 0
    docs = _chunk_state_to_documents(state, source=str(runs_path), run_id=run_id)
    if not docs:
        return 0
    rag_dir = _get_rag_dir(artifacts_root)
    rag_dir.mkdir(parents=True, exist_ok=True)
    coll = _ensure_collection(rag_dir)
    ids = [f"{run_id}_{i}" for i in range(len(docs))]
    texts = [d["text"] for d in docs]
    metadatas = [{k: v for k, v in d.items() if k != "text"} for d in docs]
    coll.add(ids=ids, documents=texts, metadatas=metadatas)
    return len(docs)


def query(
    query_text: str,
    k: int = 5,
    artifacts_root: Optional[str] = None,
    run_id_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return top-k relevant chunks from RAG. Each item: {text, source, stage, run_id, distance}."""
    rag_dir = _get_rag_dir(artifacts_root)
    if not rag_dir.exists():
        return []
    try:
        coll = _ensure_collection(rag_dir)
    except RuntimeError:
        return []
    where = None
    if run_id_filter:
        where = {"run_id": run_id_filter}
    res = coll.query(
        query_texts=[query_text],
        n_results=min(k, 20),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    out = []
    if res and res["documents"] and res["documents"][0]:
        for i, doc in enumerate(res["documents"][0]):
            meta = (res["metadatas"][0] or [{}])[i] if res.get("metadatas") else {}
            dist = (res["distances"][0] or [0])[i] if res.get("distances") else 0
            out.append({
                "text": doc,
                "source": meta.get("source", ""),
                "stage": meta.get("stage", ""),
                "run_id": meta.get("run_id", ""),
                "distance": dist,
            })
    return out


def format_retrieved_for_prompt(results: List[Dict[str, Any]], max_chars: int = 3000) -> str:
    """Turn query() results into a single string to inject into a system or user prompt."""
    if not results:
        return ""
    parts = []
    total = 0
    for r in results:
        seg = f"[{r.get('stage', '')}] {r.get('text', '')}"
        if total + len(seg) > max_chars:
            seg = seg[: max_chars - total]
        parts.append(seg)
        total += len(seg)
        if total >= max_chars:
            break
    return "\n\n---\n\n".join(parts)
