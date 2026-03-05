"""Browser-based LLM: controls local Chrome to send messages to ChatGPT web UI.

连接方式（按优先级）：
  1. CDP 模式（推荐）：attach 到已登录的 Chrome，无需重新登录。
     先运行 ./start_chrome_debug.sh 以调试端口启动 Chrome，在 Chrome 中
     登录 ChatGPT，然后直接 ./run.sh --browser 即可。
  2. Profile 模式（兜底）：用独立 profile 启动新 Chrome，需要在新窗口中登录。

Thread-safety: all calls serialized by _lock (only one ChatGPT session at a time).
"""

import atexit
import os
import time
import threading
from typing import Optional

# Reuse JSON extractor from llm.py
from tools.llm import _extract_json

# ── configuration ─────────────────────────────────────────────────────────────
CHATGPT_URL = os.environ.get("CHATGPT_URL", "https://chatgpt.com/")

# CDP: port of the already-running Chrome (start_chrome_debug.sh sets this)
CHROME_DEBUG_PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))

# Fallback profile (only used when CDP connection fails)
DEFAULT_BOT_PROFILE = os.path.expanduser("~/.chatgpt-bot-profile")
CHROME_PROFILE_DIR = os.environ.get("CHROME_PROFILE_DIR", DEFAULT_BOT_PROFILE)

# ── singletons ────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_pw = None
_browser = None  # set only for CDP mode; None for persistent-context mode
_ctx = None
_page = None

# ── DOM selectors (ordered by priority/stability) ─────────────────────────────
_INPUT_SELECTORS = [
    "#prompt-textarea",
    "textarea[data-id='root']",
    "div[contenteditable='true'][tabindex='0']",
    "div[contenteditable='true']",
]

_SEND_SELECTORS = [
    "button[data-testid='send-button']",
    "button[aria-label='Send message']",
    "button[aria-label='Send prompt']",
    "button[type='submit']",
]

_STOP_SELECTORS = [
    "button[aria-label='Stop streaming']",
    "button[aria-label='Stop generating']",
    "[data-testid='stop-button']",
    "button[aria-label*='Stop']",
]

_RESPONSE_SELECTORS = [
    "[data-message-author-role='assistant']",
    "[data-testid='bot-message']",
]


# ── browser lifecycle ─────────────────────────────────────────────────────────

def _ensure_browser() -> None:
    """Initialize browser once; reused across all calls in a pipeline run.

    Strategy:
      1. Try CDP attach to already-running Chrome (user is already logged in).
      2. Fall back to launching a new Chrome with a dedicated profile.
    """
    global _pw, _browser, _ctx, _page
    if _page is not None:
        return

    from playwright.sync_api import sync_playwright

    _pw = sync_playwright().start()

    # ── 1. Try CDP: attach to already-running Chrome ──────────────────────────
    cdp_url = f"http://localhost:{CHROME_DEBUG_PORT}"
    try:
        _browser = _pw.chromium.connect_over_cdp(cdp_url)
        # Reuse the first existing context (carries the user's login cookies)
        _ctx = _browser.contexts[0] if _browser.contexts else _browser.new_context()
        print(f"[browser_llm] ✓ 已连接到运行中的 Chrome (port {CHROME_DEBUG_PORT})")
    except Exception as e:
        # ── 2. Fall back: launch a new browser with persistent profile ─────────
        _browser = None
        print(f"[browser_llm] 未找到调试端口 {CHROME_DEBUG_PORT} 上的 Chrome ({e})")
        print(f"[browser_llm] 提示: 运行 ./start_chrome_debug.sh 可让 bot 复用已登录的 Chrome")
        print(f"[browser_llm] 回退：启动新浏览器，Profile: {CHROME_PROFILE_DIR}")
        os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
        try:
            _ctx = _pw.chromium.launch_persistent_context(
                user_data_dir=CHROME_PROFILE_DIR,
                headless=False,
                channel="chrome",
                args=["--no-first-run", "--no-default-browser-check"],
            )
        except Exception:
            _ctx = _pw.chromium.launch_persistent_context(
                user_data_dir=CHROME_PROFILE_DIR,
                headless=False,
            )

    # Open a dedicated tab for bot use (leaves user's existing tabs untouched)
    _page = _ctx.new_page()
    _page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=30_000)
    _wait_for_input_ready(timeout=20.0)
    atexit.register(_shutdown_browser)


def _shutdown_browser() -> None:
    global _pw, _browser, _ctx, _page
    try:
        if _page:
            _page.close()
    except Exception:
        pass
    # If we launched the browser ourselves, close it; if we attached via CDP, leave it running
    if _browser is None:
        try:
            if _ctx:
                _ctx.close()
        except Exception:
            pass
    try:
        if _pw:
            _pw.stop()
    except Exception:
        pass
    _page = _ctx = _browser = _pw = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _wait_for_input_ready(timeout: float = 15.0) -> bool:
    """Return True when the ChatGPT input area becomes visible."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for sel in _INPUT_SELECTORS:
            try:
                el = _page.query_selector(sel)
                if el and el.is_visible():
                    return True
            except Exception:
                pass
        time.sleep(0.3)
    return False  # May be on login screen; caller handles


def _go_new_chat() -> None:
    """Navigate to a fresh ChatGPT conversation."""
    _page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=30_000)
    if not _wait_for_input_ready(15.0):
        print("[browser_llm] WARNING: input not found after navigation — "
              "may need to log in. Open the browser and log in to ChatGPT.")
        # Wait longer in case the page is still loading
        _wait_for_input_ready(30.0)


def _fill_input(text: str) -> None:
    """Fill the ChatGPT input box with text, compatible with React's virtual DOM."""
    for sel in _INPUT_SELECTORS:
        try:
            el = _page.wait_for_selector(sel, timeout=5_000, state="visible")
            if not el:
                continue
            tag = el.evaluate("e => e.tagName").lower()
            el.click()
            time.sleep(0.15)

            if tag == "textarea":
                # React-compatible: use native value setter + dispatch events
                _page.evaluate(
                    """([sel, val]) => {
                        const el = document.querySelector(sel);
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLTextAreaElement.prototype, 'value').set;
                        setter.call(el, val);
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                    }""",
                    [sel, text],
                )
            else:
                # contenteditable div
                _page.evaluate(
                    """([sel, val]) => {
                        const el = document.querySelector(sel);
                        el.focus();
                        el.innerText = val;
                        el.dispatchEvent(new InputEvent('input', {bubbles: true}));
                    }""",
                    [sel, text],
                )
            time.sleep(0.2)
            return
        except Exception:
            continue
    raise RuntimeError(
        "ChatGPT input field not found. "
        "Make sure you are logged in — run ./setup_browser_profile.sh first."
    )


def _click_send() -> None:
    """Click the send button (or press Enter as fallback)."""
    for sel in _SEND_SELECTORS:
        try:
            btn = _page.wait_for_selector(sel, timeout=3_000, state="visible")
            if btn and btn.is_enabled():
                btn.click()
                return
        except Exception:
            continue
    _page.keyboard.press("Enter")


def _is_generating() -> bool:
    """True while ChatGPT is streaming a response."""
    for sel in _STOP_SELECTORS:
        try:
            el = _page.query_selector(sel)
            if el and el.is_visible():
                return True
        except Exception:
            pass
    return False


def _wait_for_completion(start_timeout: float = 15.0, max_wait: float = 300.0) -> None:
    """Wait for generation to start, then wait for it to finish."""
    # Phase 1: wait for the stop button to appear (generation started)
    deadline = time.time() + start_timeout
    while time.time() < deadline:
        if _is_generating():
            break
        time.sleep(0.2)

    # Phase 2: wait for the stop button to disappear (generation done)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if not _is_generating():
            break
        time.sleep(0.5)

    time.sleep(0.8)  # Small stability buffer after stream ends


def _get_last_response() -> str:
    """Extract the text of the last assistant message."""
    for sel in _RESPONSE_SELECTORS:
        try:
            els = _page.query_selector_all(sel)
            if els:
                text = els[-1].inner_text().strip()
                if text:
                    return text
        except Exception:
            pass

    # Broad fallback: find any rendered markdown block
    for sel in [".markdown", ".prose", "[class*='markdown']"]:
        try:
            els = _page.query_selector_all(sel)
            if els:
                text = els[-1].inner_text().strip()
                if text:
                    return text
        except Exception:
            pass

    raise RuntimeError(
        "Could not extract assistant response from the ChatGPT page. "
        "The DOM structure may have changed — check browser_llm.py selectors."
    )


# ── public API ────────────────────────────────────────────────────────────────

def call_llm_browser(
    system: str,
    user: str,
    json_mode: bool = False,
    max_tokens: Optional[int] = None,  # ignored (no token limit in web UI)
) -> str:
    """Send system+user prompt to ChatGPT via browser; return response text.

    All calls are serialized by a lock — ChatGPT web only supports one active
    conversation at a time per browser session.
    """
    json_suffix = ""
    if json_mode:
        json_suffix = (
            "\n\nIMPORTANT: Your entire response MUST be valid JSON only. "
            "Start your response with { and end with }. "
            "No markdown code fences, no explanation text, no prose. "
            "Output raw JSON immediately."
        )

    # Combine system + user into a single message (web UI has no system role)
    combined = (
        f"[SYSTEM INSTRUCTIONS]\n{system}{json_suffix}\n\n"
        f"[USER MESSAGE]\n{user}"
    )

    with _lock:
        _ensure_browser()
        _go_new_chat()
        _fill_input(combined)
        _click_send()
        _wait_for_completion()
        response = _get_last_response()

    if json_mode:
        response = _extract_json(response)

    return response
