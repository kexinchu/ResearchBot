"""Configuration: load from config.yaml (primary) with env var fallbacks.

Config file search order:
  1. ./config.yaml  (project-local)
  2. ~/.researchbot/config.yaml  (user-global)

Every field can also be set via environment variable (takes precedence over config.yaml).
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Config file loading ───────────────────────────────────────────────────────

_CONFIG_CACHE: Optional[Dict[str, Any]] = None


def _find_config_file() -> Optional[Path]:
    """Find config.yaml in CWD or ~/.researchbot/."""
    candidates = [
        Path.cwd() / "config.yaml",
        Path.home() / ".researchbot" / "config.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_config() -> Dict[str, Any]:
    """Load config.yaml into a flat dict. Cached after first call."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    path = _find_config_file()
    if path is None:
        _CONFIG_CACHE = {}
        return _CONFIG_CACHE

    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            data = {}
        _CONFIG_CACHE = data
    except Exception as e:
        print(f"[config] Warning: failed to load {path}: {e}")
        _CONFIG_CACHE = {}

    return _CONFIG_CACHE


def _get(yaml_section: str, yaml_key: str, env_var: str, default: Any = "") -> Any:
    """Get a config value. Priority: env var > config.yaml > default."""
    # 1. Environment variable (highest priority)
    env_val = os.environ.get(env_var, "").strip()
    if env_val:
        return env_val

    # 2. config.yaml
    cfg = _load_config()
    section = cfg.get(yaml_section) or {}
    if isinstance(section, dict) and yaml_key in section:
        val = section[yaml_key]
        if val is not None:
            return val

    return default


def reload_config() -> None:
    """Force reload config.yaml (useful after writing a new config file)."""
    global _CONFIG_CACHE
    _CONFIG_CACHE = None


# ── LLM ───────────────────────────────────────────────────────────────────────

@property
def _openai_api_key():
    return _get("llm", "api_key", "OPENAI_API_KEY", "")

# Module-level attributes (read on access via _get)
def get_openai_api_key() -> str:
    return _get("llm", "api_key", "OPENAI_API_KEY", "")

def get_openai_base_url() -> Optional[str]:
    val = _get("llm", "base_url", "OPENAI_BASE_URL", "")
    return val if val else None

def get_model() -> str:
    return _get("llm", "model", "RESEARCHBOT_MODEL", "gpt-4o-mini")

# Backward-compatible module-level constants (read once at import; prefer get_* functions)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL")
MODEL = os.environ.get("RESEARCHBOT_MODEL", "gpt-4o-mini")

# ── Browser mode ──────────────────────────────────────────────────────────────

USE_BROWSER_LLM: bool = (
    os.environ.get("RESEARCHBOT_LLM", "").strip().lower() == "browser"
)

def set_use_browser_llm(use_browser: bool) -> None:
    global USE_BROWSER_LLM
    USE_BROWSER_LLM = use_browser

# ── Zotero ────────────────────────────────────────────────────────────────────

def get_zotero_library_id() -> str:
    return str(_get("zotero", "library_id", "ZOTERO_LIBRARY_ID", ""))

def get_zotero_api_key() -> str:
    return str(_get("zotero", "api_key", "ZOTERO_API_KEY", ""))

def get_zotero_library_type() -> str:
    return str(_get("zotero", "library_type", "ZOTERO_LIBRARY_TYPE", "user"))

# Backward-compatible module-level constants
ZOTERO_LIBRARY_ID = os.environ.get("ZOTERO_LIBRARY_ID", "")
ZOTERO_API_KEY = os.environ.get("ZOTERO_API_KEY", "")
ZOTERO_LIBRARY_TYPE = os.environ.get("ZOTERO_LIBRARY_TYPE", "user")

# ── Obsidian ──────────────────────────────────────────────────────────────────

def get_obsidian_vault_path() -> str:
    return str(_get("obsidian", "vault_path", "RESEARCHBOT_OBSIDIAN_VAULT",
                     str(Path.home() / "ObsidianVault")))

OBSIDIAN_VAULT_PATH = os.environ.get(
    "RESEARCHBOT_OBSIDIAN_VAULT",
    str(Path.home() / "ObsidianVault"),
)

# ── RAG ───────────────────────────────────────────────────────────────────────

def get_rag_dir() -> str:
    return str(_get("rag", "dir", "RESEARCHBOT_RAG_DIR",
                     str(Path.home() / ".researchbot" / "rag")))

def get_rag_embedding_model() -> str:
    return str(_get("rag", "embedding_model", "RESEARCHBOT_RAG_EMBEDDING_MODEL",
                     "all-MiniLM-L6-v2"))

def get_hf_token() -> Optional[str]:
    """HuggingFace token for downloading gated/private models."""
    val = _get("rag", "hf_token", "HF_TOKEN", "")
    return val if val else None

# ── Paper type taxonomy ───────────────────────────────────────────────────────

DEFAULT_PAPER_TYPES: List[str] = [
    "ANNS",
    "RAG",
    "Diffusion-Language-Model",
    "LLM-Opt",
    "Agentic-OS",
    "KV-Cache",
    "LLM-Security",
    "Memory",
    "Deterministic-LLM",
    "Other",
]

def get_paper_types() -> List[str]:
    """Return configured paper types."""
    # Env var
    env = os.environ.get("RESEARCHBOT_PAPER_TYPES", "").strip()
    if env:
        return [t.strip() for t in env.split(",") if t.strip()]
    # config.yaml
    cfg = _load_config()
    types = (cfg.get("paper_types") or cfg.get("taxonomy", {}).get("paper_types"))
    if types and isinstance(types, list):
        return types
    return DEFAULT_PAPER_TYPES


# ── Config file template ─────────────────────────────────────────────────────

CONFIG_TEMPLATE = """\
# ResearchBot Configuration
# Place this file at ./config.yaml (project-local) or ~/.researchbot/config.yaml (global)
# All fields can also be set via environment variables (env vars take precedence)

# ── LLM ──────────────────────────────────────────────────────────────────────
# Required: at least api_key must be set (here or via OPENAI_API_KEY env var)
llm:
  api_key: ""                      # OpenAI API key (or compatible provider key)
                                    # Env: OPENAI_API_KEY
  base_url: ""                     # Custom API endpoint (leave empty for OpenAI default)
                                    # Examples: https://api.deepseek.com/v1
                                    #           http://localhost:8000/v1  (local vLLM)
                                    # Env: OPENAI_BASE_URL
  model: "gpt-4o-mini"            # Model name
                                    # Env: RESEARCHBOT_MODEL

# ── Zotero ───────────────────────────────────────────────────────────────────
# Optional but recommended. If not configured, paper recording skips Zotero.
#
# How to get these values:
#   1. Go to https://www.zotero.org/settings/keys
#   2. Click "Create new private key"
#   3. Check "Allow library access" and "Allow write access"
#   4. Save — you'll see your API key
#   5. Your library_id is the number in your Zotero profile URL:
#      https://www.zotero.org/users/<library_id>/library
#      Or find it at https://www.zotero.org/settings/keys (shown as "Your userID")
zotero:
  api_key: ""                      # Zotero API key
                                    # Env: ZOTERO_API_KEY
  library_id: ""                   # Your Zotero user ID (numeric)
                                    # Env: ZOTERO_LIBRARY_ID
  library_type: "user"             # "user" for personal library, "group" for shared
                                    # Env: ZOTERO_LIBRARY_TYPE

# ── Obsidian ─────────────────────────────────────────────────────────────────
# Required: path to your Obsidian vault folder.
#
# ResearchBot creates these folders inside your vault:
#   Papers-<paper_type>/  — paper reading notes (e.g. Papers-ANNS, Papers-RAG)
#   Idea/                 — research ideas
#   Explore/              — exploration reports
#
# How to find your vault path:
#   - Open Obsidian → Settings (gear icon) → look at the vault path at the top
#   - Or find it in Finder/Explorer: your vault is just a normal folder
obsidian:
  vault_path: "~/ObsidianVault"    # Absolute path to your Obsidian vault
                                    # Env: RESEARCHBOT_OBSIDIAN_VAULT

# ── RAG ──────────────────────────────────────────────────────────────────────
# Optional. Enables semantic search across your notes during explore/experiment.
# Requires: pip install researchbot[rag]
#
# After configuration, run: researchbot index
# This builds the vector index from your Obsidian vault.
rag:
  dir: "~/.researchbot/rag"       # Where to store the ChromaDB vector database
                                    # Env: RESEARCHBOT_RAG_DIR
  embedding_model: "all-MiniLM-L6-v2"  # sentence-transformers model for embeddings
                                         # Env: RESEARCHBOT_RAG_EMBEDDING_MODEL
  hf_token: ""                    # HuggingFace token (for gated model downloads)
                                    # Get at: https://huggingface.co/settings/tokens
                                    # Env: HF_TOKEN

# ── Paper Type Taxonomy ──────────────────────────────────────────────────────
# Categories for automatic paper classification.
# The classifier uses keyword matching + LLM to assign each paper a type.
# You can customize this list to match your research areas.
paper_types:
  - ANNS
  - RAG
  - Diffusion-Language-Model
  - LLM-Opt
  - Agentic-OS
  - KV-Cache
  - LLM-Security
  - Memory
  - Deterministic-LLM
  - Other
"""
