"""Browser-based LLM: controls local Chrome to send messages to ChatGPT web UI.

连接方式（参考 OpenClaw Zero Token，默认不占用你的主浏览器）：

  1. 独立浏览器模式（默认）：用单独 profile 启动一个 Chrome 窗口，仅给 bot 使用。
     - 首次运行会弹出该窗口，在其中登录 ChatGPT 即可；之后同一 profile 保持登录。
     - 你的日常 Chrome 无需开调试模式，互不影响。
  2. CDP 模式（可选）：attach 到已用调试端口启动的 Chrome（如想复用已登录的浏览器时）。
     - 设置环境变量 EFFICIENT_RESEARCH_USE_CHROME_CDP=1，并先运行 ./start_chrome_debug.sh，
       再执行 ./run.sh --browser。

Thread-safety: all calls serialized by _lock (only one ChatGPT session at a time).
"""

import atexit
import json
import os
import time
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reuse JSON extractor from llm.py
from tools.llm import _extract_json

# ── configuration ─────────────────────────────────────────────────────────────
CHATGPT_URL = os.environ.get("CHATGPT_URL", "https://chatgpt.com/")

# When True: try CDP attach first (needs start_chrome_debug.sh). When False/unset: use
# dedicated profile only, so user's main browser is unaffected.
USE_CHROME_CDP = os.environ.get("EFFICIENT_RESEARCH_USE_CHROME_CDP", "").strip().lower() in ("1", "true", "yes")

# CDP: port of the already-running Chrome (start_chrome_debug.sh sets this)
CHROME_DEBUG_PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))

# Dedicated profile for bot-only Chrome (default mode); also fallback when CDP fails or is disabled.
DEFAULT_BOT_PROFILE = os.path.expanduser("~/.chatgpt-bot-profile")
CHROME_PROFILE_DIR = os.environ.get("CHROME_PROFILE_DIR", DEFAULT_BOT_PROFILE)

# Optional: load cookies from file so the opened page is already logged in (e.g. ChatGPT).
# Export cookies from your normal browser (where you're logged in) to a JSON file, then set this.
# See README "浏览器模式 · 自动登录（Cookie 导入）".
COOKIE_FILE = os.environ.get("EFFICIENT_RESEARCH_COOKIE_FILE", "").strip()

# ── singletons ────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_pw = None
_browser = None  # set only for CDP mode; None for persistent-context mode
_ctx = None
_page = None

# One task in one session (see docs/BROWSER_LLM_OPTIMIZATION.md): pipeline runs
# start_browser_session() at start and end_browser_session() at end. While
# _in_session is True, the first call does _go_new_chat() then send; subsequent
# calls only append a user message in the same conversation (no navigation).
_in_session = False
_session_message_count = 0

# Retry once on transient extraction/input failures (e.g. DOM not ready)
_MAX_CALL_RETRIES = 1 + int(os.environ.get("EFFICIENT_RESEARCH_BROWSER_RETRIES", "1"))

# Minimum seconds between two browser LLM calls (avoid rate limit / 429; keep workflow sustainable)
_MIN_CALL_INTERVAL = float(os.environ.get("EFFICIENT_RESEARCH_BROWSER_MIN_INTERVAL", "5"))
_last_call_time = 0.0

# When True, prepend a short instruction to use thinking/reasoning (for ChatGPT o1 or models with thinking)
USE_THINKING_MODE = os.environ.get("EFFICIENT_RESEARCH_BROWSER_THINKING", "").strip().lower() in ("1", "true", "yes")

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

def _load_cookies_from_file(path: str) -> List[Dict[str, Any]]:
    """Load cookies from JSON array or Netscape cookies.txt. Returns list of dicts for context.add_cookies()."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return []
    cookies: List[Dict[str, Any]] = []
    with open(p, "r", encoding="utf-8") as f:
        raw = f.read()
    if p.suffix.lower() == ".txt":
        # Netscape format: domain\tflag\tpath\tsecure\texpiration\tname\tvalue
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _flag, path_str, secure_str, expiry, name, value = parts[:7]
            cookie = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path_str,
            }
            try:
                cookie["expires"] = int(expiry)
            except ValueError:
                cookie["expires"] = -1
            cookie["secure"] = secure_str.upper() == "TRUE"
            cookies.append(cookie)
    else:
        # JSON: array of { name, value, domain, path, ... }
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            data = [data]
        for c in data:
            if not isinstance(c, dict) or "name" not in c or "value" not in c:
                continue
            cookie = {"name": c["name"], "value": c["value"]}
            if "url" in c:
                cookie["url"] = c["url"]
            else:
                cookie["domain"] = c.get("domain", "")
                cookie["path"] = c.get("path", "/")
            if "expires" in c:
                cookie["expires"] = int(c["expires"])
            if "secure" in c:
                cookie["secure"] = bool(c["secure"])
            if "httpOnly" in c:
                cookie["httpOnly"] = bool(c["httpOnly"])
            if "sameSite" in c:
                cookie["sameSite"] = c["sameSite"]
            cookies.append(cookie)
    return cookies


def _normalize_cookies_for_chatgpt(cookies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure each cookie has url and secure so they apply to CHATGPT_URL (HTTPS)."""
    base = (CHATGPT_URL.split("?")[0] or CHATGPT_URL).rstrip("/")
    if not base.endswith("/"):
        base += "/"
    is_https = base.lower().startswith("https://")
    out = []
    for c in cookies:
        cookie = {"name": c["name"], "value": c["value"], "url": base}
        if is_https:
            cookie["secure"] = True
        exp = c.get("expires")
        if exp is not None and int(exp) != 0:
            cookie["expires"] = int(exp)
        if "sameSite" in c and c["sameSite"] in ("Strict", "Lax", "None"):
            cookie["sameSite"] = c["sameSite"]
        out.append(cookie)
    return out


def _inject_cookies_if_configured(context) -> None:
    """If EFFICIENT_RESEARCH_COOKIE_FILE is set, load cookies and add to context (so first page is logged in)."""
    if not COOKIE_FILE:
        return
    cookies = _load_cookies_from_file(COOKIE_FILE)
    if not cookies:
        print(f"[browser_llm] 未从 COOKIE 文件读取到有效 cookie: {COOKIE_FILE}")
        return
    cookies = _normalize_cookies_for_chatgpt(cookies)
    try:
        context.add_cookies(cookies)
        print(f"[browser_llm] 已从文件注入 {len(cookies)} 条 cookie（已按 {CHATGPT_URL} 归一化），打开页面时将使用该登录态。")
    except Exception as e:
        print(f"[browser_llm] 注入 cookie 失败: {e}")


def _goto_chatgpt_with_retry(page, max_attempts: int = 3) -> None:
    """Navigate to ChatGPT; retry on transient network errors (e.g. ERR_SOCKET_NOT_CONNECTED right after launch)."""
    last_err = None
    for attempt in range(max_attempts):
        if attempt > 0:
            wait = 3 + attempt * 2
            print(f"[browser_llm] 导航重试 {attempt + 1}/{max_attempts}，{wait}s 后重试…")
            time.sleep(wait)
        try:
            page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=30_000)
            return
        except Exception as e:
            last_err = e
            err_msg = str(e).lower()
            if "err_socket_not_connected" in err_msg or "err_connection_refused" in err_msg or "net::" in err_msg:
                continue
            raise
    raise last_err


def _apply_stealth_scripts(page) -> None:
    """Run before first navigation: hide navigator.webdriver to reduce bot verification prompts."""
    try:
        # Run before page scripts; delete from prototype first, then override on instance if needed
        page.add_init_script(
            """
            (function() {
                try {
                    var proto = Object.getPrototypeOf(navigator);
                    if (proto && 'webdriver' in proto) delete proto.webdriver;
                    Object.defineProperty(navigator, 'webdriver', { get: function() { return undefined; }, configurable: true, enumerable: true });
                } catch (e) {}
            })();
            """
        )
    except Exception:
        pass


def _launch_dedicated_chrome() -> None:
    """Launch a Chrome window with a dedicated profile (does not affect user's main browser)."""
    global _pw, _browser, _ctx, _page
    from playwright.sync_api import sync_playwright
    if _pw is None:
        _pw = sync_playwright().start()
    _browser = None
    print(f"[browser_llm] 使用独立浏览器 (Profile: {CHROME_PROFILE_DIR})，不影响日常使用的 Chrome。")
    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
    # Stealth: reduce "verify you're not a robot" — hide automation flags (see docs/BROWSER_LLM_OPTIMIZATION.md)
    _chrome_args = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=AutomationControlled",
        "--disable-blink-features=AutomationControlled",
    ]
    _launch_kw = {
        "user_data_dir": CHROME_PROFILE_DIR,
        "headless": False,
        "args": _chrome_args,
        "ignore_default_args": ["--enable-automation"],
    }
    try:
        _ctx = _pw.chromium.launch_persistent_context(channel="chrome", **_launch_kw)
    except Exception:
        _fallback_args = [a for a in _chrome_args if "AutomationControlled" not in a]
        _ctx = _pw.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_DIR,
            headless=False,
            args=_fallback_args,
            ignore_default_args=["--enable-automation"],
        )
    _page = _ctx.new_page()
    _apply_stealth_scripts(_page)
    _page.set_viewport_size({"width": 1280, "height": 800})
    # Brief wait so Chrome network stack is ready (avoids ERR_SOCKET_NOT_CONNECTED on first goto)
    time.sleep(2)
    _goto_chatgpt_with_retry(_page)
    # Inject cookies after first visit so they apply to this origin, then reload to send them
    if COOKIE_FILE:
        cookies = _load_cookies_from_file(COOKIE_FILE)
        if cookies:
            cookies = _normalize_cookies_for_chatgpt(cookies)
            try:
                _ctx.add_cookies(cookies)
                print(f"[browser_llm] 已注入 {len(cookies)} 条 cookie，正在重载页面以应用登录态…")
                _page.reload(wait_until="domcontentloaded", timeout=30_000)
            except Exception as e:
                print(f"[browser_llm] 注入 cookie 失败: {e}")
    _wait_for_input_ready(timeout=20.0)
    atexit.register(_shutdown_browser)


def _ensure_browser() -> None:
    """Initialize browser once; reused across all calls in a pipeline run.

    Default: launch a dedicated Chrome with its own profile (no debug mode on your main browser).
    If EFFICIENT_RESEARCH_USE_CHROME_CDP=1: try CDP attach first, then fall back to dedicated.
    """
    global _pw, _browser, _ctx, _page
    if _page is not None:
        return

    from playwright.sync_api import sync_playwright

    if USE_CHROME_CDP:
        # Optional: attach to user's debug-mode Chrome (./start_chrome_debug.sh)
        _pw = sync_playwright().start()
        cdp_url = f"http://localhost:{CHROME_DEBUG_PORT}"
        try:
            _browser = _pw.chromium.connect_over_cdp(cdp_url)
            _ctx = _browser.contexts[0] if _browser.contexts else _browser.new_context()
            print(f"[browser_llm] ✓ 已连接到调试端口 Chrome (port {CHROME_DEBUG_PORT})")
            _page = _ctx.new_page()
            _apply_stealth_scripts(_page)
            _page.set_viewport_size({"width": 1280, "height": 800})
            _goto_chatgpt_with_retry(_page)
            if COOKIE_FILE:
                cookies = _load_cookies_from_file(COOKIE_FILE)
                if cookies:
                    cookies = _normalize_cookies_for_chatgpt(cookies)
                    try:
                        _ctx.add_cookies(cookies)
                        print(f"[browser_llm] 已注入 {len(cookies)} 条 cookie，正在重载页面以应用登录态…")
                        _page.reload(wait_until="domcontentloaded", timeout=30_000)
                    except Exception as e:
                        print(f"[browser_llm] 注入 cookie 失败: {e}")
            _wait_for_input_ready(timeout=20.0)
            atexit.register(_shutdown_browser)
            return
        except Exception as e:
            print(f"[browser_llm] CDP 连接失败 ({e})，改用独立浏览器。")
            try:
                _pw.stop()
            except Exception:
                pass
            _pw = _browser = _ctx = _page = None

    _launch_dedicated_chrome()


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

def _is_login_page() -> bool:
    """True if current page looks like ChatGPT login/auth (need to log in)."""
    try:
        url = (_page.url or "").strip().lower()
        if "auth/login" in url or "auth/signup" in url:
            return True
        # Some redirects use fragment or path
        if "/login" in url and ("openai.com" in url or "chatgpt.com" in url):
            return True
    except Exception:
        pass
    return False


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
        if _is_login_page():
            print("[browser_llm] 检测到登录页 — 请在弹出的浏览器窗口中登录 ChatGPT，登录成功后 pipeline 会继续。")
        else:
            print("[browser_llm] WARNING: input not found after navigation — "
                  "may need to log in. Open the browser and log in to ChatGPT.")
        # Wait longer in case the page is still loading or user is logging in
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
    # Hint login page when raising
    if _is_login_page():
        raise RuntimeError(
            "ChatGPT 输入框未找到，当前在登录页。请在弹出的浏览器窗口中完成登录后再重试。"
        )
    raise RuntimeError(
        "ChatGPT input field not found. "
        "Make sure you are logged in — open the browser window and log in to ChatGPT."
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
    """Wait for generation to start, then wait for it to finish. Log progress every 30s."""
    # Phase 1: wait for the stop button to appear (generation started)
    deadline = time.time() + start_timeout
    while time.time() < deadline:
        if _is_generating():
            break
        time.sleep(0.2)

    # Phase 2: wait for the stop button to disappear (generation done)
    deadline = time.time() + max_wait
    last_log = time.time()
    while time.time() < deadline:
        if not _is_generating():
            break
        if time.time() - last_log >= 30.0:
            elapsed = int(time.time() - (deadline - max_wait))
            print(f"[browser_llm] 仍在生成中… 已等待 {elapsed}s（最长 {int(max_wait)}s）")
            last_log = time.time()
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

    if _is_login_page():
        raise RuntimeError(
            "无法获取回复：当前页面为登录页，会话可能已过期。请先在浏览器中重新登录 ChatGPT。"
        )
    raise RuntimeError(
        "Could not extract assistant response from the ChatGPT page. "
        "The DOM structure may have changed — check browser_llm.py selectors."
    )


# ── public API: session lifecycle ─────────────────────────────────────────────

def start_browser_session() -> None:
    """Mark start of a pipeline run. Subsequent call_llm_browser(same_session=True)
    will reuse the same conversation (no new chat per call) until end_browser_session()."""
    global _in_session, _session_message_count
    with _lock:
        _in_session = True
        _session_message_count = 0


def end_browser_session() -> None:
    """Mark end of a pipeline run. Next pipeline will start a new conversation."""
    global _in_session, _session_message_count
    with _lock:
        _in_session = False
        _session_message_count = 0


def call_llm_browser(
    system: str,
    user: str,
    json_mode: bool = False,
    max_tokens: Optional[int] = None,  # ignored (no token limit in web UI)
    same_session: bool = True,
) -> str:
    """Send system+user prompt to ChatGPT via browser; return response text.

    When same_session is True and start_browser_session() was called (e.g. by
    the pipeline), the first call opens a new chat; later calls append a user
    message in the same conversation without navigating away (one task, one
    session). All calls are serialized by a lock.
    """
    global _session_message_count
    json_suffix = ""
    if json_mode:
        json_suffix = (
            "\n\nIMPORTANT: Your entire response MUST be valid JSON only. "
            "Start your response with { and end with }. "
            "No markdown code fences, no explanation text, no prose. "
            "Output raw JSON immediately."
        )

    # Combine system + user into a single message (web UI has no system role)
    thinking_prefix = ""
    if USE_THINKING_MODE:
        thinking_prefix = (
            "Use your thinking/reasoning capability. Think step by step where it helps quality. "
            "Then provide a clear, complete response.\n\n"
        )
    combined = (
        f"[SYSTEM INSTRUCTIONS]\n{thinking_prefix}{system}{json_suffix}\n\n"
        f"[USER MESSAGE]\n{user}"
    )

    response = ""
    global _last_call_time
    for attempt in range(_MAX_CALL_RETRIES):
        try:
            with _lock:
                _ensure_browser()
                # Rate limit: avoid requesting GPT too fast (sustainable long runs)
                now = time.time()
                if _last_call_time > 0 and _MIN_CALL_INTERVAL > 0:
                    elapsed = now - _last_call_time
                    if elapsed < _MIN_CALL_INTERVAL:
                        wait = _MIN_CALL_INTERVAL - elapsed
                        print(f"[browser_llm] 请求间隔 {wait:.1f}s（控制频率，避免限流）…")
                        time.sleep(wait)
                if same_session and _in_session and _session_message_count >= 1:
                    _fill_input(combined)
                    _click_send()
                    _wait_for_completion()
                    response = _get_last_response()
                    _session_message_count += 1
                else:
                    if same_session and _in_session:
                        pass
                    _go_new_chat()
                    _fill_input(combined)
                    _click_send()
                    _wait_for_completion()
                    response = _get_last_response()
                    if same_session and _in_session:
                        _session_message_count = 1
                _last_call_time = time.time()
            break
        except RuntimeError as e:
            msg = str(e)
            retriable = any(
                x in msg for x in ("DOM", "extract", "输入", "登录", "input field", "获取回复", "未找到")
            )
            if attempt < _MAX_CALL_RETRIES - 1 and retriable:
                print(f"[browser_llm] 临时错误，2s 后重试 ({e})")
                time.sleep(2)
            else:
                raise

    if json_mode:
        response = _extract_json(response)

    return response
