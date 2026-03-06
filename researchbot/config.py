"""Configuration: LLM and API keys (env or defaults)."""
import os

# ── Cloud API (OpenAI-compatible) ─────────────────────────────
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL")
MODEL = os.environ.get("EFFICIENT_RESEARCH_MODEL", "gpt-4o-mini")

# ── Browser mode (ChatGPT web UI via Playwright) ─────────────
USE_BROWSER_LLM: bool = (
    os.environ.get("EFFICIENT_RESEARCH_LLM", "").strip().lower() == "browser"
)

def set_use_browser_llm(use_browser: bool) -> None:
    global USE_BROWSER_LLM
    USE_BROWSER_LLM = use_browser
