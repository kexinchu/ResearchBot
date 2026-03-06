"""LLM caller (OpenAI-compatible) for agents."""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

# ── retry configuration ──────────────────────────────────────────────────────
MAX_LLM_RETRIES = int(os.environ.get("EFFICIENT_RESEARCH_LLM_RETRIES", "3"))
RETRY_BASE_DELAY = float(os.environ.get("EFFICIENT_RESEARCH_RETRY_DELAY", "2.0"))

# ── response cache ───────────────────────────────────────────────────────────
_CACHE_DIR = os.environ.get("EFFICIENT_RESEARCH_CACHE_DIR", "").strip()
_cache_enabled = bool(_CACHE_DIR)


def _cache_key(system: str, user: str, model: str, json_mode: bool) -> str:
    blob = f"{model}|{json_mode}|{system}|{user}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Optional[str]:
    if not _cache_enabled:
        return None
    p = Path(_CACHE_DIR) / f"{key}.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get("response")
        except Exception:
            pass
    return None


def _cache_set(key: str, response: str) -> None:
    if not _cache_enabled:
        return
    p = Path(_CACHE_DIR)
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{key}.json").write_text(
        json.dumps({"response": response, "ts": time.time()}, ensure_ascii=False),
        encoding="utf-8",
    )


def get_client():
    from openai import OpenAI
    import config
    kwargs = {"api_key": config.OPENAI_API_KEY or "sk-placeholder"}
    if config.OPENAI_BASE_URL:
        kwargs["base_url"] = config.OPENAI_BASE_URL
    return OpenAI(**kwargs)


def get_model() -> str:
    import config
    return config.MODEL


def _unwrap_single_list(text: str) -> str:
    """If text is a JSON array containing exactly one dict, return that dict as JSON string."""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
            return json.dumps(parsed[0])
    except (json.JSONDecodeError, Exception):
        pass
    return text


def _extract_json(text: str) -> str:
    """Try multiple strategies to extract valid JSON from LLM output."""
    # 1. Direct parse
    try:
        json.loads(text)
        return _unwrap_single_list(text)
    except json.JSONDecodeError:
        pass
    # 2. Markdown code block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return _unwrap_single_list(candidate)
        except json.JSONDecodeError:
            pass
    # 3. First valid JSON object or array
    for start_ch, end_ch in [('{', '}'), ('[', ']')]:
        start = text.find(start_ch)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i, ch in enumerate(text[start:], start):
            if esc:
                esc = False
                continue
            if ch == '\\' and in_str:
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == start_ch:
                depth += 1
            elif ch == end_ch:
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        json.loads(candidate)
                        return _unwrap_single_list(candidate)
                    except json.JSONDecodeError:
                        break
    return text


def _is_valid_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, Exception):
        return False


def _is_browser_mode() -> bool:
    import config
    return bool(config.USE_BROWSER_LLM)


def call_llm(
    system: str,
    user: str,
    model: Optional[str] = None,
    json_mode: bool = False,
    max_tokens: Optional[int] = None,
) -> str:
    """Returns assistant text. If json_mode, extracts and returns cleaned JSON string.

    Features:
    - Retry with exponential backoff on transient errors
    - Optional disk cache (set EFFICIENT_RESEARCH_CACHE_DIR to enable)
    """
    if _is_browser_mode():
        from tools.browser_llm import call_llm_browser
        return call_llm_browser(system, user, json_mode=json_mode, max_tokens=max_tokens)

    model = model or get_model()

    # Check cache first
    ck = _cache_key(system, user, model, json_mode)
    cached = _cache_get(ck)
    if cached is not None:
        return cached

    kwargs: Any = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(MAX_LLM_RETRIES):
        try:
            client = get_client()
            r = client.chat.completions.create(**kwargs)
            text = r.choices[0].message.content or ""

            if json_mode:
                text = _extract_json(text)
                if not _is_valid_json(text) and attempt < MAX_LLM_RETRIES - 1:
                    print(f"[llm] JSON parse failed on attempt {attempt + 1}, retrying...", flush=True)
                    kwargs["messages"][-1]["content"] = (
                        user.rstrip() +
                        "\n\nCRITICAL: Your previous response was not valid JSON. "
                        "You MUST respond with ONLY a valid JSON object. Start with { and end with }. "
                        "No markdown, no explanation, no code fences."
                    )
                    time.sleep(RETRY_BASE_DELAY)
                    continue

            _cache_set(ck, text)
            return text

        except Exception as e:
            last_error = e
            err_msg = str(e).lower()
            retriable = any(k in err_msg for k in [
                "429", "rate", "timeout", "connection", "502", "503", "504",
                "overloaded", "server_error", "internal",
            ])
            if retriable and attempt < MAX_LLM_RETRIES - 1:
                wait = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"[llm] Transient error on attempt {attempt + 1}/{MAX_LLM_RETRIES}: {e}. Retrying in {wait:.1f}s...", flush=True)
                time.sleep(wait)
            else:
                raise

    raise last_error  # type: ignore
