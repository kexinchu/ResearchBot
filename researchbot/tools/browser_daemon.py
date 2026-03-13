"""Browser Daemon: persistent background process holding a Playwright browser.

Keeps the browser + ChatGPT tab alive across multiple CLI invocations within the
same shell session.  CLI commands communicate with the daemon via HTTP on localhost.

Lifecycle:
  1. First `call_llm_browser()` detects no daemon → spawns one as a subprocess.
  2. Subsequent calls (even from different `researchbot` processes) POST to the daemon.
  3. Daemon auto-exits after IDLE_TIMEOUT seconds of inactivity (default 30 min).
  4. `researchbot browser stop` or shell exit kills the daemon.

State files (in ~/.researchbot/):
  browser_daemon.pid   — daemon PID
  browser_daemon.port  — HTTP port the daemon listens on
"""

import atexit
import json
import os
import signal
import socket
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ── paths ────────────────────────────────────────────────────────────────────
STATE_DIR = Path.home() / ".researchbot"
PID_FILE = STATE_DIR / "browser_daemon.pid"
PORT_FILE = STATE_DIR / "browser_daemon.port"

IDLE_TIMEOUT = int(os.environ.get("RESEARCHBOT_BROWSER_IDLE_TIMEOUT", "1800"))  # 30 min


# ── daemon state ─────────────────────────────────────────────────────────────
_last_activity = time.time()
_browser_lock = threading.Lock()


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_state(pid: int, port: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))
    PORT_FILE.write_text(str(port))


def _cleanup_state() -> None:
    for f in (PID_FILE, PORT_FILE):
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass


def read_daemon_info() -> tuple:
    """Return (pid, port) or (None, None) if daemon state files don't exist."""
    try:
        pid = int(PID_FILE.read_text().strip())
        port = int(PORT_FILE.read_text().strip())
        return pid, port
    except Exception:
        return None, None


def is_daemon_alive() -> bool:
    """Check if a daemon process is running."""
    pid, port = read_daemon_info()
    if pid is None:
        return False
    # Check if PID is alive
    try:
        os.kill(pid, 0)
    except OSError:
        _cleanup_state()
        return False
    # Check if port is responding
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        _cleanup_state()
        return False


def stop_daemon() -> bool:
    """Stop the running daemon. Returns True if stopped."""
    pid, _ = read_daemon_info()
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait briefly for cleanup
        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.3)
            except OSError:
                break
        _cleanup_state()
        return True
    except OSError:
        _cleanup_state()
        return False


# ── HTTP handler ─────────────────────────────────────────────────────────────

class _DaemonHandler(BaseHTTPRequestHandler):
    """Handles /chat and /health endpoints."""

    def log_message(self, format, *args):
        # Suppress default logging
        pass

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "ok", "pid": os.getpid()})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        global _last_activity
        _last_activity = time.time()

        if self.path == "/chat":
            self._handle_chat()
        elif self.path == "/new_session":
            self._handle_new_session()
        elif self.path == "/shutdown":
            self._respond(200, {"status": "shutting down"})
            threading.Thread(target=self._delayed_shutdown, daemon=True).start()
        else:
            self._respond(404, {"error": "not found"})

    def _handle_chat(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
        except Exception as e:
            self._respond(400, {"error": f"bad request: {e}"})
            return

        system = body.get("system", "")
        user = body.get("user", "")
        json_mode = body.get("json_mode", False)
        max_tokens = body.get("max_tokens")
        same_session = body.get("same_session", True)

        try:
            with _browser_lock:
                response = _do_browser_call(system, user, json_mode, max_tokens, same_session)
            self._respond(200, {"response": response})
        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _handle_new_session(self):
        """Reset session so next /chat opens a new ChatGPT conversation."""
        global _daemon_session_started
        try:
            with _browser_lock:
                from researchbot.tools.browser_llm import end_browser_session
                end_browser_session()
                _daemon_session_started = False
            self._respond(200, {"status": "session reset, next chat will open new conversation"})
        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _delayed_shutdown():
        time.sleep(0.5)
        os._exit(0)


# ── browser call (runs inside daemon) ────────────────────────────────────────

_daemon_session_started = False


def _do_browser_call(system, user, json_mode, max_tokens, same_session):
    """Perform a browser LLM call using the persistent browser in this daemon process.

    Uses _call_llm_browser_inprocess (NOT call_llm_browser) to avoid recursion
    back into the daemon client.

    The daemon keeps a persistent session: the first call opens a new chat,
    subsequent calls append to the same conversation (reusing the ChatGPT session).
    """
    global _daemon_session_started
    from researchbot.tools.browser_llm import (
        _call_llm_browser_inprocess, start_browser_session,
    )

    # Start a persistent session on first call — all subsequent calls reuse it
    if not _daemon_session_started:
        start_browser_session()
        _daemon_session_started = True

    return _call_llm_browser_inprocess(
        system=system, user=user, json_mode=json_mode,
        max_tokens=max_tokens, same_session=True,  # Always reuse session in daemon
    )


# ── idle watchdog ────────────────────────────────────────────────────────────

def _idle_watchdog(server: HTTPServer):
    """Shut down the daemon after IDLE_TIMEOUT seconds of inactivity."""
    while True:
        time.sleep(30)
        if time.time() - _last_activity > IDLE_TIMEOUT:
            print(f"[browser_daemon] Idle for {IDLE_TIMEOUT}s, shutting down.", flush=True)
            _cleanup_state()
            server.shutdown()
            os._exit(0)


# ── daemon main ──────────────────────────────────────────────────────────────

def run_daemon():
    """Start the browser daemon HTTP server. Called as a subprocess."""
    global _last_activity
    _last_activity = time.time()

    port = _find_free_port()
    _write_state(os.getpid(), port)
    atexit.register(_cleanup_state)

    # Handle SIGTERM gracefully
    def _handle_sigterm(signum, frame):
        print("[browser_daemon] Received SIGTERM, shutting down.", flush=True)
        _cleanup_state()
        os._exit(0)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    server = HTTPServer(("127.0.0.1", port), _DaemonHandler)
    print(f"[browser_daemon] Started on port {port} (PID {os.getpid()}), "
          f"idle timeout {IDLE_TIMEOUT}s", flush=True)

    # Start idle watchdog
    watchdog = threading.Thread(target=_idle_watchdog, args=(server,), daemon=True)
    watchdog.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup_state()
        server.server_close()


# ── client: send request to daemon ───────────────────────────────────────────

def daemon_chat(system: str, user: str, json_mode: bool = False,
                max_tokens: int = None, same_session: bool = True,
                timeout: float = 960.0) -> str:
    """Send a chat request to the running daemon. Returns response text.

    Raises ConnectionError if daemon is not reachable.
    Raises RuntimeError on daemon-side errors.
    """
    _, port = read_daemon_info()
    if port is None:
        raise ConnectionError("Browser daemon is not running")

    import urllib.request
    import urllib.error

    payload = {
        "system": system,
        "user": user,
        "json_mode": json_mode,
        "same_session": same_session,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise ConnectionError(f"Cannot reach browser daemon: {e}")
    except Exception as e:
        raise ConnectionError(f"Daemon request failed: {e}")

    if "error" in result:
        raise RuntimeError(f"Browser daemon error: {result['error']}")

    return result.get("response", "")


def daemon_new_session() -> bool:
    """Tell the daemon to start a fresh ChatGPT conversation.

    Returns True if successful, False if daemon is not running.
    """
    _, port = read_daemon_info()
    if port is None:
        return False

    import urllib.request
    import urllib.error

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/new_session",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            json.loads(resp.read())
        return True
    except Exception:
        return False


def ensure_daemon_running() -> int:
    """Start daemon if not running. Returns the daemon port."""
    if is_daemon_alive():
        _, port = read_daemon_info()
        return port

    import subprocess

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Start daemon as detached subprocess
    daemon_cmd = [
        sys.executable, "-m", "researchbot.tools.browser_daemon"
    ]

    # Use subprocess to start daemon, detached from parent
    proc = subprocess.Popen(
        daemon_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # Detach from parent process group
    )

    # Wait for daemon to write its port file (up to 30s for browser launch)
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(0.5)
        if PORT_FILE.exists() and PID_FILE.exists():
            try:
                port = int(PORT_FILE.read_text().strip())
                # Verify it's actually listening
                with socket.create_connection(("127.0.0.1", port), timeout=2):
                    print(f"[browser_daemon] Daemon ready on port {port} (PID {proc.pid})")
                    return port
            except (OSError, ValueError):
                continue

    # If we get here, daemon failed to start — read its output for debug
    proc.terminate()
    output = ""
    try:
        output = proc.stdout.read().decode("utf-8", errors="replace")[:500]
    except Exception:
        pass
    raise RuntimeError(f"Browser daemon failed to start within 60s. Output:\n{output}")


# ── module entry point (for subprocess) ──────────────────────────────────────

if __name__ == "__main__":
    run_daemon()
