"""Configuration: LLM and API keys (env or defaults).是否使用本地模型由入参决定，见 set_use_local_llm()。"""
import os
from typing import Tuple

# 是否使用本地大模型（vLLM 等）。默认从环境变量 EFFICIENT_RESEARCH_LLM 读取，也可由 CLI --local 通过 set_use_local_llm(True) 设置
_use_local_llm: bool | None = None

def _compute_llm_config(use_local: bool) -> Tuple[str, str | None, str]:
    if use_local:
        api_key = os.environ.get("OPENAI_API_KEY", "no-key-required")
        base_url = os.environ.get("OPENAI_BASE_URL") or "http://127.0.0.1:8000/v1"
        model = os.environ.get("EFFICIENT_RESEARCH_MODEL") or "Qwen3.5-35B-A3B-GPTQ-Int4"
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("OPENAI_BASE_URL")
        model = os.environ.get("EFFICIENT_RESEARCH_MODEL", "gpt-4o-mini")
    return api_key, base_url, model

def set_use_local_llm(use_local: bool) -> None:
    """由入参（如 CLI --local）决定是否使用本地大模型，调用后全局生效。"""
    global _use_local_llm, USE_LOCAL_LLM, OPENAI_API_KEY, OPENAI_BASE_URL, MODEL
    _use_local_llm = use_local
    USE_LOCAL_LLM = use_local
    OPENAI_API_KEY, OPENAI_BASE_URL, MODEL = _compute_llm_config(use_local)

# 初始化：入参未设置时用环境变量
USE_LOCAL_LLM = _use_local_llm if _use_local_llm is not None else (
    os.environ.get("EFFICIENT_RESEARCH_LLM", "").strip().lower() == "local"
)
OPENAI_API_KEY, OPENAI_BASE_URL, MODEL = _compute_llm_config(USE_LOCAL_LLM)
