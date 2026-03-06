#!/usr/bin/env bash
# start_chrome_debug.sh（可选）
# 以远程调试模式启动 Chrome，供 ResearchBot 在「CDP 模式」下 attach 使用。
# 参考 OpenClaw Zero Token：专用 user-data-dir（不占用主浏览器）、单实例、CDP 参数、就绪等待。
#
# 默认推荐：直接 ./run.sh --browser，会用独立 profile 开一个 Chrome，不占用日常浏览器。
# 仅当希望复用「已登录的调试端口 Chrome」时：
#   export EFFICIENT_RESEARCH_USE_CHROME_CDP=1
#   ./start_chrome_debug.sh
#   ./run.sh --browser

set -e

PORT="${CHROME_DEBUG_PORT:-9222}"

# ─── 跨平台：OS 与 Chrome 路径、专用数据目录 ─────────────────────────────
detect_os() {
  case "$OSTYPE" in
    darwin*)  echo "mac" ;;
    msys*|cygwin*|mingw*) echo "win" ;;
    *)
      if grep -qi microsoft /proc/version 2>/dev/null; then echo "wsl"; else echo "linux"; fi
      ;;
  esac
}

detect_chrome() {
  local os="${1:-$(detect_os)}"
  if [[ -n "$CHROME_BIN" && -f "$CHROME_BIN" ]]; then
    echo "$CHROME_BIN"
    return
  fi
  case "$os" in
    mac)
      local mac_paths=(
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        "/Applications/Chromium.app/Contents/MacOS/Chromium"
      )
      for p in "${mac_paths[@]}"; do [[ -f "$p" ]] && echo "$p" && return; done
      command -v google-chrome >/dev/null 2>&1 && echo "google-chrome" && return
      ;;
    linux|wsl)
      local linux_paths=(
        "/usr/bin/google-chrome-stable"
        "/usr/bin/google-chrome"
        "/usr/bin/chromium"
        "/usr/bin/chromium-browser"
      )
      for p in "${linux_paths[@]}"; do [[ -f "$p" ]] && echo "$p" && return; done
      for cmd in google-chrome google-chrome-stable chromium chromium-browser; do
        command -v "$cmd" >/dev/null 2>&1 && echo "$cmd" && return
      done
      ;;
    win)
      [[ -n "$PROGRAMFILES" ]] && [[ -f "$PROGRAMFILES/Google/Chrome/Application/chrome.exe" ]] && echo "$PROGRAMFILES/Google/Chrome/Application/chrome.exe" && return
      ;;
  esac
  echo ""
}

detect_user_data_dir() {
  local os="${1:-$(detect_os)}"
  case "$os" in
    mac)  echo "$HOME/Library/Application Support/ResearchBot-Chrome-Debug" ;;
    win)  echo "${LOCALAPPDATA:-$HOME/AppData/Local}/ResearchBot-Chrome-Debug" ;;
    wsl)  echo "$HOME/.config/researchbot-chrome-debug" ;;
    *)    echo "$HOME/.config/researchbot-chrome-debug" ;;
  esac
}

OS=$(detect_os)
CHROME_BIN=$(detect_chrome "$OS")
USER_DATA_DIR="${CHROME_PROFILE_DIR:-$(detect_user_data_dir "$OS")}"

if [[ -z "$CHROME_BIN" ]]; then
  echo "错误: 未找到 Chrome / Chromium。"
  echo "请安装 Chrome 或设置 CHROME_BIN 或 CHROME_PROFILE_DIR。"
  case "$OS" in
    linux) echo "  Ubuntu/Debian: sudo apt install google-chrome-stable" ;;
    mac)  echo "  下载: https://www.google.com/chrome/" ;;
    win)  echo "  下载: https://www.google.com/chrome/" ;;
  esac
  exit 1
fi

echo "=========================================="
echo " ResearchBot · Chrome 调试模式"
echo "=========================================="
echo " 系统: $OS"
echo " Chrome: $CHROME_BIN"
echo " 数据目录: $USER_DATA_DIR（专用，不影响主浏览器）"
echo " 端口: $PORT"
echo ""

# ─── 单实例：关闭已有调试 Chrome ─────────────────────────────────────
if curl -sf "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "检测到已有调试 Chrome，正在关闭…"
  pkill -f "remote-debugging-port=${PORT}" 2>/dev/null || true
  sleep 2
  if curl -sf "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
    pkill -9 -f "remote-debugging-port=${PORT}" 2>/dev/null || true
    sleep 1
  fi
  if curl -sf "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
    echo "✗ 无法关闭现有 Chrome，请手动: pkill -9 -f 'chrome.*${PORT}'"
    exit 1
  fi
  echo "✓ 已关闭"
  echo ""
fi

# ─── 启动 Chrome（CDP 参数参考 OpenClaw）────────────────────────────────
mkdir -p "$USER_DATA_DIR"
TMP_LOG="/tmp/researchbot-chrome-debug.log"
[[ ! -d /tmp ]] && TMP_LOG="$HOME/researchbot-chrome-debug.log"

echo "正在启动 Chrome 调试模式…"
# 降低「验证是否为机器人」：去掉自动化标识（与 browser_llm 一致）
"$CHROME_BIN" \
  --remote-debugging-port="${PORT}" \
  --user-data-dir="${USER_DATA_DIR}" \
  --no-first-run \
  --no-default-browser-check \
  --disable-features=AutomationControlled \
  --disable-blink-features=AutomationControlled \
  --disable-background-networking \
  --disable-sync \
  --remote-allow-origins=* \
  "https://chatgpt.com/" \
  >> "$TMP_LOG" 2>&1 &

CHROME_PID=$!
echo "日志: $TMP_LOG"
echo ""

# ─── 等待 CDP 就绪 ─────────────────────────────────────────────────────
echo "等待 Chrome 就绪…"
for _ in {1..15}; do
  if curl -sf "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
    break
  fi
  echo -n "."
  sleep 1
done
echo ""
echo ""

if curl -sf "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "✓ Chrome 调试模式已启动"
  echo ""
  echo "下一步："
  echo "  1. 设置: export EFFICIENT_RESEARCH_USE_CHROME_CDP=1"
  echo "  2. 在打开的窗口中登录 ChatGPT（如已登录可忽略）"
  echo "  3. 运行: ./run.sh --browser"
  echo ""
  echo "停止: pkill -f 'chrome.*remote-debugging-port=${PORT}'"
  echo "=========================================="
else
  echo "✗ Chrome 启动失败，请查看: $TMP_LOG"
  echo "手动尝试: \"$CHROME_BIN\" --remote-debugging-port=${PORT} --user-data-dir=\"$USER_DATA_DIR\""
  exit 1
fi
