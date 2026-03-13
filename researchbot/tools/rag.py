"""Local RAG: index Obsidian notes and Zotero papers for context retrieval.

Uses ChromaDB (vector store) + sentence-transformers (embeddings).
Indexes paper notes, idea notes, and explore reports from the Obsidian vault.

Usage:
  - index_obsidian_vault() to scan and index all notes
  - index_paper_note(path) to index a single note after creation
  - query(topic, k=10) to retrieve relevant context
  - format_retrieved_for_prompt(results) to inject into LLM prompts

Requires: pip install researchbot[rag]
"""
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_COLLECTION_NAME = "researchbot"


def _get_rag_dir() -> Path:
    from researchbot.config import get_rag_dir
    return Path(get_rag_dir()).expanduser().resolve()


def _get_client(rag_dir: Path):
    import chromadb
    from chromadb.config import Settings
    return chromadb.PersistentClient(path=str(rag_dir), settings=Settings(anonymized_telemetry=False))


def _get_embedding_function():
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        from researchbot.config import get_rag_embedding_model, get_hf_token

        # Set HF token for gated model downloads if configured
        hf_token = get_hf_token()
        if hf_token:
            os.environ.setdefault("HF_TOKEN", hf_token)

        return SentenceTransformerEmbeddingFunction(
            model_name=get_rag_embedding_model(),
            normalize_embeddings=True,
        )
    except Exception as e:
        print(f"[rag] Embedding function init failed: {e}")
        return None


def _ensure_collection(rag_dir: Path):
    client = _get_client(rag_dir)
    ef = _get_embedding_function()
    if ef is None:
        raise RuntimeError(
            "RAG requires chromadb and sentence-transformers. Run: pip install researchbot[rag]"
        )
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=ef,
        metadata={"description": "ResearchBot paper notes, ideas, and research context"},
    )


# ── Parse Obsidian notes ──────────────────────────────────────────────────────

def _parse_obsidian_note(filepath: Path) -> Optional[Dict[str, Any]]:
    """Parse an Obsidian markdown note with YAML frontmatter.

    Returns dict with 'frontmatter' and 'body', or None if not a valid note.
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    frontmatter = {}
    body = content

    # Parse YAML frontmatter
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if m:
        try:
            import yaml
            frontmatter = yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass
        body = m.group(2).strip()

    if not frontmatter and not body:
        return None

    return {"frontmatter": frontmatter, "body": body, "path": str(filepath)}


def _note_to_documents(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert a parsed Obsidian note into indexable document chunks."""
    fm = parsed.get("frontmatter", {})
    body = parsed.get("body", "")
    path = parsed.get("path", "")
    note_type = fm.get("type", "unknown")
    title = fm.get("title", Path(path).stem if path else "untitled")

    docs = []

    # Index metadata summary as one document
    authors = fm.get("authors", [])
    if isinstance(authors, list):
        authors_str = ", ".join(str(a) for a in authors[:10])
    else:
        authors_str = str(authors)

    meta_text = f"Paper: {title}"
    if authors_str:
        meta_text += f" by {authors_str}"
    if fm.get("year"):
        meta_text += f" ({fm['year']})"
    if fm.get("venue"):
        meta_text += f" at {fm['venue']}"
    if fm.get("paper_type"):
        meta_text += f" [{fm['paper_type']}]"

    tags = fm.get("tags", [])
    if tags and isinstance(tags, list):
        meta_text += f" Tags: {', '.join(str(t) for t in tags)}"

    docs.append({
        "text": meta_text,
        "source": path,
        "note_type": note_type,
        "title": str(title),
        "doc_part": "metadata",
    })

    # Index body sections (split by ## headings)
    sections = re.split(r"\n## ", body)
    for section in sections:
        section = section.strip()
        if not section or len(section) < 20:
            continue
        # Prefix with title for context
        chunk = f"[{title}] {section[:1500]}"
        docs.append({
            "text": chunk,
            "source": path,
            "note_type": note_type,
            "title": str(title),
            "doc_part": "content",
        })

    return docs


# ── Index operations ──────────────────────────────────────────────────────────

def index_obsidian_vault(vault_path: Optional[str] = None) -> int:
    """Scan Obsidian vault and index all markdown notes into RAG.

    Returns count of documents indexed.
    """
    from researchbot.config import get_obsidian_vault_path

    vault = Path(vault_path or get_obsidian_vault_path())
    if not vault.exists():
        print(f"[rag] Vault not found: {vault}")
        return 0

    rag_dir = _get_rag_dir()
    rag_dir.mkdir(parents=True, exist_ok=True)
    coll = _ensure_collection(rag_dir)

    all_docs = []
    for md_file in vault.rglob("*.md"):
        parsed = _parse_obsidian_note(md_file)
        if parsed:
            all_docs.extend(_note_to_documents(parsed))

    if not all_docs:
        print("[rag] No notes found to index.")
        return 0

    # Use file path + part as stable ID to allow re-indexing
    ids = []
    texts = []
    metadatas = []
    for i, doc in enumerate(all_docs):
        doc_id = f"obs_{hash(doc['source'] + doc['doc_part'] + doc['text'][:50]) & 0xFFFFFFFF}_{i}"
        ids.append(doc_id)
        texts.append(doc["text"])
        metadatas.append({k: v for k, v in doc.items() if k != "text"})

    # Upsert in batches (ChromaDB has limits)
    batch_size = 500
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        coll.upsert(
            ids=ids[start:end],
            documents=texts[start:end],
            metadatas=metadatas[start:end],
        )

    print(f"[rag] Indexed {len(all_docs)} documents from {vault}")
    return len(all_docs)


def index_paper_note(filepath: str | Path) -> int:
    """Index a single paper note into RAG. Called after writing a note. Returns doc count."""
    filepath = Path(filepath)
    parsed = _parse_obsidian_note(filepath)
    if not parsed:
        return 0

    docs = _note_to_documents(parsed)
    if not docs:
        return 0

    rag_dir = _get_rag_dir()
    rag_dir.mkdir(parents=True, exist_ok=True)

    try:
        coll = _ensure_collection(rag_dir)
    except RuntimeError:
        return 0

    ids = [f"obs_{hash(d['source'] + d['doc_part'] + d['text'][:50]) & 0xFFFFFFFF}_{i}" for i, d in enumerate(docs)]
    texts = [d["text"] for d in docs]
    metadatas = [{k: v for k, v in d.items() if k != "text"} for d in docs]
    coll.upsert(ids=ids, documents=texts, metadatas=metadatas)
    return len(docs)


# ── Query ─────────────────────────────────────────────────────────────────────

def query(
    query_text: str,
    k: int = 10,
    note_type_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return top-k relevant chunks from RAG.

    Each item: {text, source, note_type, title, doc_part, distance}.
    """
    rag_dir = _get_rag_dir()
    if not rag_dir.exists():
        return []
    try:
        coll = _ensure_collection(rag_dir)
    except RuntimeError:
        return []

    where = None
    if note_type_filter:
        where = {"note_type": note_type_filter}

    res = coll.query(
        query_texts=[query_text],
        n_results=min(k, 30),
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
                "note_type": meta.get("note_type", ""),
                "title": meta.get("title", ""),
                "doc_part": meta.get("doc_part", ""),
                "distance": dist,
            })
    return out


def format_retrieved_for_prompt(results: List[Dict[str, Any]], max_chars: int = 4000) -> str:
    """Format query() results into a string to inject into LLM prompts.

    Groups by note for readability.
    """
    if not results:
        return ""

    parts = []
    total = 0
    seen_titles = set()

    for r in results:
        title = r.get("title", "?")
        prefix = f"[{r.get('note_type', '?')}]" if r.get("note_type") else ""
        seg = f"{prefix} {r.get('text', '')}"

        if total + len(seg) > max_chars:
            seg = seg[:max_chars - total]
        parts.append(seg)
        total += len(seg)
        if total >= max_chars:
            break

    return "\n\n---\n\n".join(parts)
