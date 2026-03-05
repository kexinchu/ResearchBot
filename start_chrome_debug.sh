#!/usr/bin/env bash
# start_chrome_debug.sh
# 以远程调试模式启动 Chrome，让 ResearchBot --browser 模式 attach 到已登录的 Chrome。
#
# 使用流程：
#   1. ./start_chrome_debug.sh        ← 启动带调试端口的 Chrome
#   2. 在打开的 Chrome 中登录 ChatGPT（已登录则跳过）
#   3. ./run.sh --browser             ← bot 自动 attach，无需重新登录

PORT="${CHROME_DEBUG_PORT:-9222}"
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [[ ! -f "$CHROME_BIN" ]]; then
  echo "错误: 未找到 Google Chrome: $CHROME_BIN"
  echo "请确认 Chrome 已安装，或设置环境变量 CHROME_BIN 指向正确路径。"
  exit 1
fi

# 检查端口是否已被占用（Chrome 可能已在运行）
if curl -sf "http://localhost:${PORT}/json/version" >/dev/null 2>&1; then
  echo "✓ Chrome 已在 port ${PORT} 以调试模式运行，无需重新启动。"
  echo "  直接运行 ./run.sh --browser 即可。"
  exit 0
fi

echo "正在以调试模式启动 Chrome (port ${PORT})..."
"$CHROME_BIN" \
  --remote-debugging-port="${PORT}" \
  --no-first-run \
  --no-default-browser-check \
  "https://chatgpt.com/" \
  &

echo ""
echo "Chrome 已启动。请："
echo "  1. 在打开的 Chrome 窗口中登录 ChatGPT（如已登录可忽略）"
echo "  2. 然后运行: ./run.sh --browser"
echo ""
echo "注意: 不要关闭这个 Chrome 窗口，bot 运行期间需要保持开启。"
