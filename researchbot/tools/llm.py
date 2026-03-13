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
    from researchbot.config import get_openai_api_key, get_openai_base_url
    kwargs = {"api_key": get_openai_api_key() or "sk-placeholder"}
    base_url = get_openai_base_url()
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def get_model() -> str:
    from researchbot.config import get_model as _get_model
    return _get_model()


def _unwrap_single_list(text: str) -> str:
    """If text is a JSON array containing exactly one dict, return that dict as JSON string."""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
            return json.dumps(parsed[0])
    except (json.JSONDecodeError, Exception):
        pass
    return text


def _escape_newlines_in_strings(text: str) -> str:
    """Escape literal newlines (and other control chars) inside JSON string values.

    Walks the text tracking quote state; only modifies characters inside "...".
    """
    result = []
    in_str = False
    esc = False
    for ch in text:
        if esc:
            result.append(ch)
            esc = False
            continue
        if ch == '\\' and in_str:
            result.append(ch)
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            result.append(ch)
            continue
        if in_str:
            if ch == '\n':
                result.append('\\n')
                continue
            if ch == '\r':
                result.append('\\r')
                continue
            if ch == '\t':
                result.append('\\t')
                continue
            # Strip other control characters
            if ord(ch) < 0x20:
                result.append(' ')
                continue
        result.append(ch)
    return ''.join(result)


def _repair_json_string(text: str) -> str:
    """Attempt to repair common JSON issues from browser-extracted text.

    Level 1: remove known ChatGPT citation artifacts, then escape newlines in strings.
    """
    # Remove ChatGPT citation artifacts that may have leaked into JSON
    # Pattern: source_name on its own line, then +N on next line
    text = re.sub(
        r'\n(?:arXiv|Wikipedia|Semantic Scholar|Google Scholar|'
        r'GitHub|Medium|docs|Papers with Code|OpenReview)[^\n]*\n\+\d+\n',
        ' ', text
    )
    # Standalone "+N" on its own line
    text = re.sub(r'\n\+\d+\n', ' ', text)
    # Isolated source names on their own line
    text = re.sub(r'\n(?:arXiv|Wikipedia)\n', ' ', text)

    return _escape_newlines_in_strings(text)


def _aggressive_repair_json(text: str) -> str:
    """Level 2 aggressive repair: strip anything that looks like a web UI artifact.

    Applied when standard repair fails. More likely to lose some content but
    produces parseable JSON.
    """
    # First apply standard repair
    text = _repair_json_string(text)

    # If still fails, the artifacts might be inline (not on their own lines).
    # Strip any word followed by +N that doesn't look like normal text.
    # e.g. "retrieval. arXiv +1 The paper" → "retrieval.  The paper"
    text = re.sub(
        r'(?:arXiv|Wikipedia|Semantic Scholar|Google Scholar|'
        r'GitHub|Medium|docs|Papers with Code|OpenReview)'
        r'\s*\+\d+',
        '', text
    )
    # Remove isolated "+N" (not part of math like "x+1")
    text = re.sub(r'(?<=[.,:;!?\s])\+\d+(?=[\s",.}])', '', text)
    # Remove stray superscript-like numbers after periods (e.g. ".1 2")
    text = re.sub(r'(?<=\.)\s*\d+\s+\d+\s*(?=[A-Z"])', ' ', text)
    # Collapse multiple spaces
    text = re.sub(r'  +', ' ', text)

    return text


def _try_parse(text: str) -> str:
    """Try to parse text as JSON, with escalating repair. Returns valid JSON string or None."""
    # 1. Direct parse
    try:
        json.loads(text)
        return _unwrap_single_list(text)
    except json.JSONDecodeError:
        pass
    # 2. Standard repair (escape newlines in strings, remove known artifacts)
    repaired = _repair_json_string(text)
    try:
        json.loads(repaired)
        return _unwrap_single_list(repaired)
    except json.JSONDecodeError:
        pass
    # 3. Aggressive repair (strip more patterns)
    aggressive = _aggressive_repair_json(text)
    try:
        json.loads(aggressive)
        return _unwrap_single_list(aggressive)
    except json.JSONDecodeError:
        pass
    return None


def _find_balanced_block(text: str, start_ch: str, end_ch: str) -> str:
    """Find the first balanced {..} or [..] block in text using depth tracking."""
    start = text.find(start_ch)
    if start < 0:
        return None
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
                return text[start:i + 1]
    return None


def _extract_json(text: str) -> str:
    """Try multiple strategies to extract valid JSON from LLM output.

    Strongly prefers JSON objects ({...}) over arrays ([...]) to avoid
    returning a tags array when the full note object is present but damaged.
    """
    # 1. Direct parse (with repair)
    result = _try_parse(text)
    if result:
        return result
    # 2. Markdown code block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        candidate = m.group(1).strip()
        result = _try_parse(candidate)
        if result:
            return result

    # 3. Try to find and parse a JSON object ({...}) first — strongly preferred
    obj_block = _find_balanced_block(text, '{', '}')
    if obj_block:
        result = _try_parse(obj_block)
        if result:
            return result
        # Object found but couldn't parse — try last-resort line-by-line rebuild
        result = _last_resort_json_repair(obj_block)
        if result:
            return result

    # 4. Fall back to JSON array ([...]) only if no object was found or parseable
    arr_block = _find_balanced_block(text, '[', ']')
    if arr_block:
        result = _try_parse(arr_block)
        if result:
            # Only return array if no object block existed at all
            parsed = json.loads(result)
            if obj_block and isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                # This looks like a tags array, not the main response — skip it
                pass
            else:
                return result

    # 5. If we had an object block, return best-effort even if not valid JSON
    if obj_block:
        repaired = _aggressive_repair_json(obj_block)
        return repaired

    return text


def _last_resort_json_repair(text: str) -> str:
    """Last-resort repair: rebuild JSON by extracting key-value pairs with regex.

    When all other repair strategies fail, extract "key": "value" pairs from
    the damaged JSON and reconstruct a clean object.
    """
    try:
        # Try to find all "key": "value" pairs (string values)
        str_pairs = re.findall(
            r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.|"(?=\s*,|\s*}))*?)"',
            text, re.DOTALL
        )
        # Find "key": [...] pairs (array values)
        arr_pairs = re.findall(
            r'"(\w+)"\s*:\s*(\[(?:[^\[\]]|\[(?:[^\[\]])*\])*\])',
            text
        )

        if not str_pairs and not arr_pairs:
            return None

        obj = {}
        for key, val in str_pairs:
            # Clean the value: remove artifacts, normalize whitespace
            val = re.sub(r'\s+', ' ', val).strip()
            obj[key] = val
        for key, val in arr_pairs:
            try:
                obj[key] = json.loads(val)
            except json.JSONDecodeError:
                obj[key] = val

        if obj:
            result = json.dumps(obj, ensure_ascii=False)
            json.loads(result)  # verify
            return result
    except Exception:
        pass
    return None


def _is_valid_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, Exception):
        return False


def _is_browser_mode() -> bool:
    """Auto-detect: use browser if explicitly set OR if no API key is configured."""
    from researchbot import config
    if config.USE_BROWSER_LLM:
        return True
    # No API key → fallback to browser
    api_key = config.get_openai_api_key()
    return not api_key or api_key == "sk-placeholder"


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
        from researchbot.tools.browser_llm import call_llm_browser
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
