"""Classify papers into paper_type using LLM zero-shot classification."""
import json

from researchbot.config import get_paper_types
from researchbot.models import PaperMetadata


def classify_paper(meta: PaperMetadata) -> str:
    """Classify a paper into one of the configured paper types.

    Uses LLM for zero-shot classification based on title + abstract.
    Falls back to keyword matching if LLM is unavailable.
    """
    paper_types = get_paper_types()

    # Try keyword-based first (fast, no API call)
    keyword_result = _keyword_classify(meta, paper_types)

    # If keyword gives a confident match, use it
    if keyword_result != "Other":
        return keyword_result

    # Use LLM for ambiguous cases
    try:
        return _llm_classify(meta, paper_types)
    except Exception as e:
        print(f"[classifier] LLM classification failed: {e}, using keyword fallback")
        return keyword_result


def _keyword_classify(meta: PaperMetadata, paper_types: list[str]) -> str:
    """Simple keyword-based classification."""
    text = f"{meta.title} {meta.abstract}".lower()

    keyword_map = {
        "ANNS": ["approximate nearest neighbor", "ann ", "anns", "hnsw", "ivf",
                 "faiss", "similarity search", "vector search", "vector index",
                 "vector database", "embedding search", "graph-based index",
                 "proximity graph", "quantization", "product quantization"],
        "RAG": ["retrieval-augmented", "retrieval augmented", "rag ",
                "retrieve and generate", "knowledge-grounded", "retrieval generation",
                "dense retrieval", "passage retrieval", "document retrieval",
                "re-ranking", "bi-encoder", "cross-encoder"],
        "Diffusion-Language-Model": ["diffusion model", "diffusion language", "ddpm",
                                      "score matching", "denoising", "flow matching",
                                      "continuous diffusion", "discrete diffusion",
                                      "text diffusion", "diffusion transformer"],
        "LLM-Opt": ["llm inference", "model serving", "inference optimization",
                     "speculative decoding", "model compression", "quantization",
                     "pruning", "distillation", "batching", "throughput",
                     "latency optimization", "tensor parallelism", "pipeline parallelism",
                     "flash attention", "paged attention", "vllm", "trt-llm"],
        "Agentic-OS": ["agent", "multi-agent", "agentic", "tool use", "function calling",
                        "operating system", "agent framework", "agent orchestration",
                        "autonomous agent", "planning", "react", "agent runtime"],
        "KV-Cache": ["kv cache", "key-value cache", "kv compression", "cache eviction",
                      "attention cache", "cache management", "token eviction",
                      "cache optimization", "sliding window", "sparse attention"],
        "LLM-Security": ["llm security", "jailbreak", "prompt injection", "red teaming",
                          "adversarial attack", "safety alignment", "guardrail",
                          "content filter", "harmful output", "toxicity",
                          "llm vulnerability", "watermark"],
        "Memory": ["memory management", "memory optimization", "memory efficient",
                    "memory wall", "memory bandwidth", "offloading", "swap",
                    "memory pool", "gpu memory", "memory hierarchy",
                    "long-term memory", "episodic memory", "memory augmented"],
        "Deterministic-LLM": ["deterministic", "reproducible", "consistent output",
                               "constrained generation", "structured output",
                               "formal verification", "guaranteed", "controllable generation",
                               "constrained decoding", "grammar-guided"],
    }

    best_type = "Other"
    best_count = 0
    for ptype, keywords in keyword_map.items():
        if ptype not in paper_types:
            continue
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count = count
            best_type = ptype

    return best_type


def _llm_classify(meta: PaperMetadata, paper_types: list[str]) -> str:
    """Use LLM for classification."""
    from researchbot.tools.llm import call_llm

    system = (
        "You are a research paper classifier. Given a paper's title and abstract, "
        "classify it into exactly one of the provided categories. "
        "Respond with a JSON object: {\"paper_type\": \"<category>\"}."
    )
    user = (
        f"Categories: {', '.join(paper_types)}\n\n"
        f"Title: {meta.title}\n\n"
        f"Abstract: {meta.abstract[:1500]}\n\n"
        "Classify this paper. Output JSON only."
    )
    raw = call_llm(system, user, json_mode=True, max_tokens=100)
    try:
        result = json.loads(raw)
        ptype = result.get("paper_type", "Other")
        if ptype in paper_types:
            return ptype
    except (json.JSONDecodeError, KeyError):
        pass
    return "Other"
