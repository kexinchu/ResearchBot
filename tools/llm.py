"""LLM caller (OpenAI-compatible) for agents."""
import json
import re
from typing import Any, Optional


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


def _is_local_model() -> bool:
    import config
    return bool(config.USE_LOCAL_LLM)


def _strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks emitted by Qwen3 and similar reasoning models."""
    import re
    return re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()


def _extract_json(text: str) -> str:
    """Try multiple strategies to extract valid JSON from LLM output."""
    # 1. Direct parse
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass
    # 2. Markdown code block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
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
                        return candidate
                    except json.JSONDecodeError:
                        break
    return text


def call_llm(
    system: str,
    user: str,
    model: Optional[str] = None,
    json_mode: bool = False,
    max_tokens: Optional[int] = None,
) -> str:
    """Returns assistant text. If json_mode, extracts and returns cleaned JSON string."""
    client = get_client()
    model = model or get_model()
    local = _is_local_model()

    # For local models, inject JSON instruction into the prompt instead of using
    # response_format (which some vLLM deployments don't support or enforce).
    system_effective = system
    user_effective = user
    if json_mode and local:
        if "Output valid JSON" not in system and "json" not in system.lower()[-200:]:
            system_effective = system + "\n\nIMPORTANT: You MUST output ONLY valid JSON. No markdown, no prose, no code fences. Start your response with { and end with }."
        if not user_effective.rstrip().endswith("}") and "json" not in user_effective.lower()[-100:]:
            user_effective = user_effective.rstrip() + "\n\nRespond with valid JSON only. Start immediately with { — no preamble."

    kwargs: Any = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_effective},
            {"role": "user", "content": user_effective},
        ],
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if json_mode and not local:
        # Cloud APIs: use structured response_format
        kwargs["response_format"] = {"type": "json_object"}
    elif json_mode and local:
        # Qwen3 / thinking models: disable thinking for JSON calls (faster, cleaner output)
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    r = client.chat.completions.create(**kwargs)
    text = r.choices[0].message.content or ""

    # Strip <think>...</think> blocks emitted by reasoning models (Qwen3, DeepSeek-R1, etc.)
    if local:
        text = _strip_thinking(text)

    if json_mode:
        text = _extract_json(text)

    return text
